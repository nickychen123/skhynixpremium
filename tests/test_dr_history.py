"""Tests for the generic depositary-receipt history pipeline."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

from dr_history import CASES, build, clean, premium, window_factor  # noqa: E402


class Ratios(unittest.TestCase):
    def test_infosys_one_share_per_ads(self):
        # ADR $76.47, NSE Rs 2,394.85, 43.55 rupees per dollar (Bloomberg, 5 Jul 2005) -> +39.0%
        self.assertAlmostEqual(premium(76.47, 2394.85, 43.55, ratio=1), 0.3904, places=3)

    def test_tsmc_five_shares_per_ads(self):
        self.assertAlmostEqual(premium(54.31, 200.0, 30.8, ratio=5), 0.6727, places=3)


class Windows(unittest.TestCase):
    def test_window_factor_is_half_open(self):
        w = (("2000-01-27", "2000-02-15", 2.0),)
        self.assertEqual(window_factor("2000-01-26", w), 1.0)
        self.assertEqual(window_factor("2000-01-27", w), 2.0)
        self.assertEqual(window_factor("2000-02-14", w), 2.0)
        self.assertEqual(window_factor("2000-02-15", w), 1.0)

    def test_build_applies_window_to_adr_only(self):
        adr = {"2000-01-26": 10.0, "2000-01-28": 5.0}      # Yahoo halved the ADR early (NY ex-date later)
        local = {"2000-01-26": 400.0, "2000-01-28": 200.0}  # Mumbai went ex on the 27th
        fx = {"2000-01-25": 40.0}
        rows = build(adr, local, fx, ratio=1, windows=(("2000-01-27", "2000-02-15", 2.0),))
        self.assertAlmostEqual(rows[0]["premium"], 10.0 / (400.0 / 40.0) - 1)   # 0%
        self.assertAlmostEqual(rows[1]["premium"], 10.0 / (200.0 / 40.0) - 1)   # corrected to +100%, not 0% -> -50%
        self.assertEqual(rows[1]["adr"], 10.0)


class Cleaning(unittest.TestCase):
    def test_bounds_come_from_the_case(self):
        c = CASES["infosys"]
        rows = [{"date": "2000-03-15", "adr": 1, "local": 1, "fx": 43.6, "premium": 1.36},   # real, kept
                {"date": "2011-10-24", "adr": 1, "local": 1, "fx": 1.8, "premium": -0.9}]    # bad FX, dropped
        keep, drop = clean(rows, c.fx_bounds, c.premium_bounds)
        self.assertEqual(len(keep), 1)
        self.assertEqual(drop[0]["date"], "2011-10-24")

    def test_every_case_is_internally_consistent(self):
        for c in CASES.values():
            self.assertLess(c.fx_bounds[0], c.fx_bounds[1])
            self.assertLess(c.premium_bounds[0], c.premium_bounds[1])
            self.assertGreater(c.ratio, 0)
            for start, end, f in c.adr_windows:
                self.assertLess(start, end)
                self.assertGreater(f, 0)


if __name__ == "__main__":
    unittest.main()
