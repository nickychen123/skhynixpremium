"""Tests for the derived live metrics and the venue session clock."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

import market_hours as mh  # noqa: E402
from metrics import derive, parse_book  # noqa: E402

CTX_A = {"markPx": "1200.0", "oraclePx": "1216.0", "midPx": "1200.5", "prevDayPx": "1177.1",
         "funding": "-0.0003", "openInterest": "230000", "dayNtlVlm": "277000000", "premium": "-0.0102"}
CTX_B = {"markPx": "163.4", "oraclePx": "163.43", "midPx": "163.425", "prevDayPx": "160.67",
         "funding": "-0.0000077", "openInterest": "609000", "dayNtlVlm": "89000000", "premium": "-0.00003"}
BOOK_A = {"levels": [[{"px": "1205.8", "sz": "24.681", "n": 6}], [{"px": "1205.9", "sz": "2.226", "n": 2}]]}
BOOK_B = {"levels": [[{"px": "163.7", "sz": "22.14", "n": 2}], [{"px": "163.72", "sz": "81.63", "n": 3}]]}
CTX_KRW = {"oraclePx": "1350.3", "markPx": "1350.3"}


class Derive(unittest.TestCase):
    def setUp(self):
        self.d = derive(CTX_A, CTX_B, parse_book(BOOK_A), parse_book(BOOK_B), CTX_KRW)

    def test_three_premiums(self):
        d = self.d
        self.assertAlmostEqual(d["mark_prem"], 1634.0 / 1200.0 - 1, places=9)
        self.assertAlmostEqual(d["oracle_prem"], 1634.3 / 1216.0 - 1, places=9)
        self.assertAlmostEqual(d["sell_prem"], 1637.0 / 1205.9 - 1, places=9)   # ADS bid x10 / share ask
        self.assertAlmostEqual(d["buy_prem"], 1637.2 / 1205.8 - 1, places=9)    # ADS ask x10 / share bid
        self.assertLess(d["sell_prem"], d["buy_prem"])

    def test_carry_is_short_leg_minus_long_leg(self):
        # long SKHX pays -0.0003 (receives), short SKHY receives -0.0000077 (pays): net +0.0002923/h
        self.assertAlmostEqual(self.d["carry_h"], -0.0000077 - (-0.0003), places=12)
        self.assertAlmostEqual(self.d["carry_apr"], self.d["carry_h"] * 24 * 365, places=12)

    def test_unwind_and_dollar_premium(self):
        self.assertAlmostEqual(self.d["dollar_prem"], 434.0, places=9)
        self.assertAlmostEqual(self.d["unwind"], 1 / (1634.0 / 1200.0) - 1, places=9)

    def test_implied_won_prices(self):
        self.assertAlmostEqual(self.d["krx_implied"], 1216.0 * 1350.3, places=6)
        self.assertAlmostEqual(self.d["adr_implied"], 163.43 * 10 * 1350.3, places=6)

    def test_missing_inputs_give_none_not_errors(self):
        d = derive(CTX_A, None)
        self.assertIsNone(d["mark_prem"])
        self.assertIsNone(d["carry_h"])
        self.assertIsNone(d["krx_implied"])
        d = derive({"markPx": "abc"}, CTX_B)
        self.assertIsNone(d["mark_prem"])

    def test_parse_book_handles_empty_side(self):
        b = parse_book({"levels": [[], [{"px": "10", "sz": "1", "n": 1}]]})
        self.assertIsNone(b["bid"])
        self.assertEqual(b["ask"], 10.0)
        self.assertIsNone(parse_book(None)["ask"])


class MarketHours(unittest.TestCase):
    def test_krx_open_midsession(self):
        now = datetime(2026, 9, 8, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # Tuesday
        s = mh.session_state(mh.KRX, now)
        self.assertTrue(s.is_open)
        self.assertEqual(s.until, timedelta(hours=5, minutes=30))
        self.assertEqual(s.until_label, "5h 30m")

    def test_krx_friday_evening_waits_for_monday(self):
        now = datetime(2026, 9, 4, 22, 3, tzinfo=ZoneInfo("Asia/Seoul"))  # Friday
        s = mh.session_state(mh.KRX, now)
        self.assertFalse(s.is_open)
        self.assertEqual(s.until, timedelta(days=2, hours=10, minutes=57))  # Mon 09:00

    def test_nasdaq_before_open_same_day(self):
        now = datetime(2026, 9, 4, 9, 2, tzinfo=ZoneInfo("America/New_York"))  # Friday
        s = mh.session_state(mh.NASDAQ, now)
        self.assertFalse(s.is_open)
        self.assertEqual(s.until, timedelta(minutes=28))

    def test_saturday_rolls_to_monday(self):
        now = datetime(2026, 9, 5, 12, 0, tzinfo=ZoneInfo("America/New_York"))  # Saturday
        s = mh.session_state(mh.NASDAQ, now)
        self.assertEqual(s.until, timedelta(days=1, hours=21, minutes=30))

    def test_accepts_utc_input(self):
        now = datetime(2026, 9, 8, 1, 0, tzinfo=ZoneInfo("UTC"))  # 10:00 KST Tuesday
        self.assertTrue(mh.session_state(mh.KRX, now).is_open)


if __name__ == "__main__":
    unittest.main()
