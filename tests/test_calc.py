"""Tests for the scenario calculator."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

from calc import Scenario, average_rate, breakeven_exit_premium, carry_apr, evaluate, grid  # noqa: E402


class PricePnl(unittest.TestCase):
    def test_premium_compression_seoul_flat(self):
        # 36% -> 10% on a $1,200 share: the dollar premium falls from 432 to 120, position gains 312
        r = evaluate(Scenario(1200, 0.36, 1200, 0.10, 0, 0, 0))
        self.assertAlmostEqual(r.price, 312.0)
        self.assertAlmostEqual(r.total, 312.0)

    def test_price_pnl_matches_leg_arithmetic(self):
        # long 1 share at 1200, short 10 ADS at 163.2 (=1632). Share -> 1100, ADS x10 -> 1540.
        r = evaluate(Scenario(1200, 0.36, 1100, 0.40, 0, 0, 0))
        expected = (1100 - 1200) - (1540 - 1632)
        self.assertAlmostEqual(r.price, expected)

    def test_widening_loses(self):
        r = evaluate(Scenario(1200, 0.36, 1200, 0.42, 0, 0, 0))
        self.assertLess(r.total, 0)


class FundingAndFees(unittest.TestCase):
    def test_funding_sign_convention(self):
        # negative funding on the long leg is received; zero on the short leg
        r = evaluate(Scenario(1000, 0.30, 1000, 0.30, 24, -0.001, 0.0))
        self.assertAlmostEqual(r.funding, 24 * 0.001 * 1000)
        # positive funding on the short leg is received, weighted by the (1+p) notional
        r = evaluate(Scenario(1000, 0.30, 1000, 0.30, 24, 0.0, 0.001))
        self.assertAlmostEqual(r.funding, 24 * 0.001 * 1300)

    def test_fees_charged_on_open_and_close(self):
        r = evaluate(Scenario(1000, 0.30, 1000, 0.30, 0, 0, 0, fee=0.0005))
        self.assertAlmostEqual(r.fees, 0.0005 * (1000 + 1300 + 1000 + 1300))
        self.assertAlmostEqual(r.total, -r.fees)

    def test_return_on_margin_and_annualisation(self):
        r = evaluate(Scenario(1000, 0.30, 1000, 0.20, 24 * 30, 0, 0))
        self.assertAlmostEqual(r.total, 100.0)
        self.assertAlmostEqual(r.return_on_margin(1.0), 100.0 / 2300.0)
        self.assertAlmostEqual(r.return_on_margin(5.0), 5 * 100.0 / 2300.0)
        self.assertAlmostEqual(r.annualised(1.0, 24 * 30), 100.0 / 2300.0 * 8760 / 720)


class Breakeven(unittest.TestCase):
    def test_breakeven_zeroes_total(self):
        sc = Scenario(1200, 0.36, 1150, 0.30, 24 * 20, -0.0002, -0.00001, fee=0.0005)
        p1 = breakeven_exit_premium(sc)
        r = evaluate(Scenario(sc.s0, sc.p0, sc.s1, p1, sc.hours, sc.f_a, sc.f_b, sc.fee))
        self.assertAlmostEqual(r.total, 0.0, places=6)

    def test_breakeven_without_carry_is_entry_premium_scaled(self):
        # no funding, no fees, Seoul flat: breakeven is the entry premium itself
        self.assertAlmostEqual(breakeven_exit_premium(Scenario(1200, 0.36, 1200, 0, 0, 0, 0)), 0.36)


class Helpers(unittest.TestCase):
    def test_carry_apr(self):
        self.assertAlmostEqual(carry_apr(-0.0003, -0.0000077, 0.0), (-0.0000077 + 0.0003) * 24 * 365)

    def test_average_rate(self):
        self.assertAlmostEqual(average_rate([{"fundingRate": "0.001"}, {"fundingRate": "-0.003"}]), -0.001)
        self.assertIsNone(average_rate([]))

    def test_grid_shape_and_monotonic_in_exit_premium(self):
        sc = Scenario(1200, 0.36, 1200, 0.36, 0, 0, 0)
        g = grid(sc, [0.40, 0.30, 0.20], [1, 10], leverage=1.0)
        self.assertEqual((len(g), len(g[0])), (3, 2))
        self.assertLess(g[0][0], g[1][0])
        self.assertLess(g[1][0], g[2][0])


if __name__ == "__main__":
    unittest.main()
