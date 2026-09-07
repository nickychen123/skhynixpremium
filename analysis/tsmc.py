"""TSMC ADR premium history. Thin wrapper over dr_history, kept for older imports and tests.

    python analysis/tsmc.py --csv data/tsmc_premium.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dr_history as _dr  # noqa: E402
from dr_history import CASES, load_csv, parse_fed, write_csv, yearly  # noqa: E402,F401

CASE = CASES["tsmc"]
RATIO = CASE.ratio
LISTED = CASE.listed
REPORTED = list(CASE.reported)
EVENTS = list(CASE.events)


def premium(tsm: float, tw: float, fx: float, ratio: float = RATIO) -> float:
    return _dr.premium(tsm, tw, fx, ratio)


def build(tsm: dict[str, float], tw: dict[str, float], fx: dict[str, float]) -> list[dict]:
    return _dr.build(tsm, tw, fx, RATIO)


def clean(rows: list[dict], fx_lo: float = 20.0, fx_hi: float = 45.0, p_lo: float = -0.5, p_hi: float = 1.5):
    return _dr.clean(rows, (fx_lo, fx_hi), (p_lo, p_hi))


def fetch_all() -> tuple[list[dict], list[dict]]:
    return _dr.fetch_case(CASE)


if __name__ == "__main__":
    raise SystemExit(_dr.main(["--case", "tsmc"] + sys.argv[1:]))
