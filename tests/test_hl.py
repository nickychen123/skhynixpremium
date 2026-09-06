"""Tests for the API client's pagination (no network)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

from hl import paginate  # noqa: E402


def fake_endpoint(rows: list[dict], page_size: int):
    """Mimics Hyperliquid: returns up to page_size rows with time >= start (and <= end), ascending."""
    calls = []

    def fetch(start, end):
        calls.append(start)
        sel = [r for r in rows if r["time"] >= start and (end is None or r["time"] <= end)]
        return sel[:page_size]

    return fetch, calls


class Paginate(unittest.TestCase):
    def test_walks_all_pages_without_duplicates(self):
        rows = [{"time": t * 3_600_000, "v": t} for t in range(1, 1201)]   # 1,200 hourly prints
        fetch, calls = fake_endpoint(rows, 500)
        got = paginate(fetch, 0, None)
        self.assertEqual(len(got), 1200)
        self.assertEqual([r["v"] for r in got], list(range(1, 1201)))
        self.assertEqual(len(calls), 3)   # 500 + 500 + 200

    def test_single_short_page_stops_immediately(self):
        rows = [{"time": t * 3_600_000} for t in range(1, 11)]
        fetch, calls = fake_endpoint(rows, 500)
        self.assertEqual(len(paginate(fetch, 0, None)), 10)
        self.assertEqual(len(calls), 2)   # the second call returns nothing new and ends the walk

    def test_respects_end_time(self):
        rows = [{"time": t * 3_600_000} for t in range(1, 2001)]
        fetch, _ = fake_endpoint(rows, 500)
        got = paginate(fetch, 0, 700 * 3_600_000)
        self.assertEqual(len(got), 700)

    def test_empty_endpoint(self):
        fetch, _ = fake_endpoint([], 500)
        self.assertEqual(paginate(fetch, 0, None), [])

    def test_stuck_cursor_does_not_loop_forever(self):
        # an endpoint that ignores startTime and always returns the same page
        page = [{"time": 5}, {"time": 6}]
        got = paginate(lambda s, e: page, 0, None)
        self.assertEqual(got, page)


if __name__ == "__main__":
    unittest.main()
