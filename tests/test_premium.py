"""Unit tests for the premium math and the carry backtest (standard library unittest).

Run:  python -m unittest discover -s tests -v
Set HL_LIVE=1 to also run the network smoke test against the Hyperliquid API.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

import hl  # noqa: E402
from carry_backtest import backtest, summarize  # noqa: E402
from premium import align, premium, stats, unwind_move  # noqa: E402


class PremiumMath(unittest.TestCase):
    def test_premium_uses_ten_to_one_ratio(self):
        # 10 ADSs at $163.43 = $1,634.30 vs a $1,216 share -> +34.4%
        self.assertAlmostEqual(premium(163.43, 1216.0), 0.3440, places=4)

    def test_premium_is_zero_at_parity(self):
        self.assertAlmostEqual(premium(120.0, 1200.0), 0.0, places=12)

    def test_premium_rejects_bad_share_price(self):
        with self.assertRaises(ValueError):
            premium(100.0, 0.0)

    def test_unwind_is_not_the_premium(self):
        # The brief's key arithmetic: a 36% premium unwinding to parity is -26.5% on the ADR.
        self.assertAlmostEqual(unwind_move(0.36, 0.0), -0.2647, places=4)
        self.assertAlmostEqual(unwind_move(0.36, 0.10), -0.1912, places=4)
        self.assertAlmostEqual(unwind_move(0.36, 0.36), 0.0, places=12)


class Alignment(unittest.TestCase):
    def test_align_joins_on_open_time_and_drops_gaps(self):
        share = [{"t": 1, "c": "1000"}, {"t": 2, "c": "1100"}, {"t": 3, "c": "1200"}]
        adr = [{"t": 1, "c": "120"}, {"t": 3, "c": "150"}]        # hour 2 missing on the ADR side
        rows = align(share, adr)
        self.assertEqual([r["t"] for r in rows], [1, 3])
        self.assertAlmostEqual(rows[0]["premium"], 0.20)
        self.assertAlmostEqual(rows[1]["premium"], 0.25)

    def test_align_skips_zero_share_close(self):
        rows = align([{"t": 1, "c": "0"}], [{"t": 1, "c": "100"}])
        self.assertEqual(rows, [])


class Stats(unittest.TestCase):
    def test_stats_percentile_and_z(self):
        rows = [{"premium": p} for p in (0.30, 0.32, 0.34, 0.36, 0.38)]
        s = stats(rows, current=0.36)
        self.assertEqual(s["n"], 5)
        self.assertAlmostEqual(s["mean"], 0.34)
        self.assertAlmostEqual(s["percentile"], 0.8)
        self.assertGreater(s["z"], 0)

    def test_stats_empty(self):
        self.assertEqual(stats([])["n"], 0)


class CarryBacktest(unittest.TestCase):
    def _rows(self):
        # premium widens from 20% to 30% over two hours with the share flat: price leg loses $100
        return [
            {"t": 0, "share": 1000.0, "adr10": 1200.0, "premium": 0.20},
            {"t": 3_600_000, "share": 1000.0, "adr10": 1250.0, "premium": 0.25},
            {"t": 7_200_000, "share": 1000.0, "adr10": 1300.0, "premium": 0.30},
        ]

    def test_price_leg_loses_when_premium_widens(self):
        bt = backtest(self._rows(), {}, {})
        self.assertAlmostEqual(bt[-1]["price_pnl"], -100.0)
        self.assertAlmostEqual(bt[-1]["funding_pnl"], 0.0)
        self.assertAlmostEqual(bt[-1]["drawdown"], 100.0)

    def test_funding_sign_convention(self):
        # negative SKHX funding: shorts pay longs, so the long SKHX leg RECEIVES;
        # zero SKHY funding. Hour 1: -(-0.001) * 1000 = +1.0
        fa = {3_600_000: -0.001, 7_200_000: -0.001}
        bt = backtest(self._rows(), fa, {})
        self.assertAlmostEqual(bt[1]["funding_pnl"], 1.0)
        self.assertAlmostEqual(bt[2]["funding_pnl"], 2.0)
        s = summarize(bt)
        self.assertAlmostEqual(s["funding_pnl"], 2.0)
        self.assertAlmostEqual(s["total_pnl"], -98.0)
        self.assertAlmostEqual(s["max_drawdown_usd"], 98.0)


@unittest.skipUnless(os.environ.get("HL_LIVE") == "1", "set HL_LIVE=1 to hit the live API")
class LiveSmoke(unittest.TestCase):
    def test_both_markets_exist_and_ratio_is_sane(self):
        ctx = hl.asset_ctx("xyz")
        self.assertIn(hl.SKHX, ctx)
        self.assertIn(hl.SKHY, ctx)
        p = premium(float(ctx[hl.SKHY]["oraclePx"]), float(ctx[hl.SKHX]["oraclePx"]))
        # A wildly wrong ratio would show up as a premium of several hundred percent or -90%.
        self.assertGreater(p, -0.5)
        self.assertLess(p, 1.5)


if __name__ == "__main__":
    unittest.main()
