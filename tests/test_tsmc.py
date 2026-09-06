"""Tests for the TSMC premium pipeline's pure parts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

from tsmc import build, clean, parse_fed, premium, yearly  # noqa: E402


class Premium(unittest.TestCase):
    def test_reported_jan_2000_example(self):
        # brief: ADR $54.31, Taipei NT$200, FX 30.8, 5 shares per ADS -> about 67%
        self.assertAlmostEqual(premium(54.31, 200.0, 30.8), 0.6727, places=3)

    def test_parity(self):
        self.assertAlmostEqual(premium(100.0, 640.0, 32.0), 0.0)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            premium(100.0, 0.0, 32.0)


class FedParser(unittest.TestCase):
    HTML = ('<tr><th>&nbsp;3-<ABBR title="January">Jan-</ABBR>00&nbsp;</th><td>&nbsp;31.5700&nbsp;</td></tr>'
            '<tr><th>&nbsp;4-<ABBR title="January">Jan-</ABBR>00&nbsp;</th><td><ABBR title="No Data">&nbsp;ND&nbsp;</ABBR></td></tr>'
            '<tr><th>&nbsp;29-<ABBR title="December">Dec-</ABBR>99&nbsp;</th><td>&nbsp;31.4000&nbsp;</td></tr>'
            '<tr><th>&nbsp;15-Aug-2026&nbsp;</th><td>&nbsp;30.1200&nbsp;</td></tr>')

    def test_parses_dates_years_and_skips_nd(self):
        got = parse_fed(self.HTML)
        self.assertEqual(got, {"2000-01-03": 31.57, "1999-12-29": 31.4, "2026-08-15": 30.12})


class Build(unittest.TestCase):
    def test_joins_on_taiwan_dates_and_forward_fills_fx(self):
        tsm = {"2000-01-04": 20.0, "2000-01-05": 21.0, "2000-01-07": 22.0}
        tw = {"2000-01-04": 100.0, "2000-01-05": 100.0, "2000-01-06": 100.0, "2000-01-07": 100.0}
        fx = {"2000-01-03": 32.0, "2000-01-06": 30.0}
        rows = build(tsm, tw, fx)
        self.assertEqual([r["date"] for r in rows], ["2000-01-04", "2000-01-05", "2000-01-07"])  # 01-06 has no NY close
        self.assertEqual(rows[0]["fx"], 32.0)   # forward-filled from 01-03
        self.assertEqual(rows[2]["fx"], 30.0)   # 01-06 rate applies on 01-07
        self.assertAlmostEqual(rows[0]["premium"], 20.0 / (5 * 100.0 / 32.0) - 1)

    def test_clean_drops_vendor_errors_and_keeps_extremes(self):
        rows = [{"date": "2000-01-26", "tsm": 1, "tw": 1, "fx": 30.8, "premium": 1.15},    # real bubble extreme, kept
                {"date": "2011-10-24", "tsm": 1, "tw": 1, "fx": 1.8015, "premium": -0.937},  # bad FX tick, dropped
                {"date": "2002-11-01", "tsm": 1, "tw": 1, "fx": 34.7, "premium": -0.007}]   # small discount, kept
        keep, drop = clean(rows)
        self.assertEqual([r["date"] for r in keep], ["2000-01-26", "2002-11-01"])
        self.assertEqual([r["date"] for r in drop], ["2011-10-24"])

    def test_yearly_buckets(self):
        rows = [{"date": "2000-01-04", "premium": 0.5}, {"date": "2000-06-01", "premium": 0.3}, {"date": "2001-01-04", "premium": 0.1}]
        y = yearly(rows)
        self.assertEqual([r["year"] for r in y], ["2000", "2001"])
        self.assertAlmostEqual(y[0]["mean"], 0.4)
        self.assertEqual(y[0]["days"], 2)


if __name__ == "__main__":
    unittest.main()
