"""Depositary-receipt premium histories from free sources (TSMC, Infosys).

    premium = ADR / (shares_per_ADS * local / FX) - 1

Sources: Yahoo Finance chart API for split-adjusted daily closes; Federal Reserve H.10
historical files for daily USD exchange rates from 1990 (Yahoo's FX history is short and
carries bad ticks). Both closes are split-adjusted by the same corporate events, so today's
ADS ratio holds through the adjusted series; where the two markets' ex-dates differ, a
window factor restores the economic ratio for those few days (see Case.adr_windows).

Usage:  python analysis/dr_history.py --case infosys --csv data/infosys_premium.csv
"""
from __future__ import annotations

import argparse
import bisect
import csv
import html
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"}
FED_BASE = "https://www.federalreserve.gov/releases/h10/hist/"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass(frozen=True)
class Case:
    key: str
    name: str
    adr: str                     # Yahoo symbol of the depositary receipt
    local: str                   # Yahoo symbol of the home-market share
    fx_yahoo: str                # Yahoo FX symbol, units of local currency per USD
    fx_fed: tuple[str, ...]      # Fed H.10 file stems, e.g. ("dat96_ta", "dat00_ta")
    ratio: float                 # home shares per ADS, in today's terms
    listed: str                  # ADR listing date
    fx_bounds: tuple[float, float]
    premium_bounds: tuple[float, float]
    adr_windows: tuple[tuple[str, str, float], ...] = ()   # (start, end_exclusive, factor) applied to the ADR close
    reported: tuple[tuple[str, float, str], ...] = ()      # (date, premium %, note) from the literature, for markers
    events: tuple[tuple[str, str], ...] = ()
    note: str = ""


CASES: dict[str, Case] = {
    "tsmc": Case(
        key="tsmc", name="TSMC", adr="TSM", local="2330.TW", fx_yahoo="TWD=X", fx_fed=("dat96_ta", "dat00_ta"),
        ratio=5, listed="1997-10-08", fx_bounds=(20.0, 45.0), premium_bounds=(-0.5, 1.5),
        reported=(("1999-07-13", 31.75, "reported 12-month low"),
                  ("2000-01-26", 115.0, "reported intraday high"),
                  ("2000-01-28", 67.0, "reported close (Economist: about 70%)")),
        events=(("1999-05-11", "Board adopts ADS conversion-sale policy"),
                ("2000-06-15", "ADS offering priced about 43% above Taipei"),
                ("2003-10-02", "Taiwan abolishes the QFII system")),
        note="Taiwan share history starts January 2000, 27 months after the ADR listed.",
    ),
    "infosys": Case(
        key="infosys", name="Infosys", adr="INFY", local="INFY.NS", fx_yahoo="INR=X", fx_fed=("dat96_in", "dat00_in"),
        ratio=1, listed="1999-03-11", fx_bounds=(30.0, 120.0), premium_bounds=(-0.5, 2.5),
        # Yahoo dates the 2000 split 2000-01-27 in Mumbai and 2000-02-15 in New York, but the adjusted
        # series are continuous through that window without a factor (checked: +100% on 26 Jan,
        # +106% on 27 Jan), so no window correction is applied. The 2004 ratio change (half a share
        # to one share per ADS) is absorbed by the 4:1 local vs 2:1 ADR adjustments.
        adr_windows=(),
        reported=(("2000-03-15", 136.0, "Lamont: March 2000"),
                  ("2001-07-01", 57.0, "Saxena 2006: 2001 mean"), ("2002-07-01", 61.0, "Saxena 2006: 2002 mean"),
                  ("2003-07-01", 46.0, "Saxena 2006: 2003 mean"), ("2004-07-01", 49.0, "Saxena 2006: 2004 mean"),
                  ("2005-07-01", 36.0, "Saxena 2006: 2005 mean"), ("2005-07-05", 39.04, "Bloomberg table, 5 Jul 2005")),
        events=(("2002-02-13", "RBI: two-way fungibility, re-conversion up to cancellations"),
                ("2002-11-15", "RBI allows sponsored ADR issues against existing shares"),
                ("2003-07-15", "Sponsored ADS offering, $294m"),
                ("2005-06-15", "Sponsored ADS offering, $1.1bn"),
                ("2006-11-15", "Sponsored ADS offering, $1.6bn (ADS share 14% to 19%)"),
                ("2012-12-12", "Listing moves from Nasdaq to NYSE")),
        note="Full history from the first ADR trading day. Before July 2004 each ADS represented half a share; "
             "the adjusted series carries today's 1:1 ratio throughout.",
    ),
}


def _get(url: str, timeout: int = 25) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def yahoo_daily(symbol: str) -> dict[str, float]:
    """Split-adjusted daily closes keyed by ISO date (UTC date of the bar)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1=0&period2={int(time.time())}&interval=1d"
    res = json.loads(_get(url))["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    return {time.strftime("%Y-%m-%d", time.gmtime(t)): float(c) for t, c in zip(res["timestamp"], closes) if c is not None}


def parse_fed(text: str) -> dict[str, float]:
    """Parse an H.10 historical page: rows like '3-Jan-00 31.5700' or 'ND' for no data."""
    t = html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")
    out = {}
    for d, mon, y, v in re.findall(r"(\d{1,2})-\s*([A-Za-z]{3})-\s*(\d{2,4})\s+([\d.]+|ND)", t):
        if v == "ND" or mon.lower() not in MONTHS:
            continue
        yy = int(y)
        if yy < 100:
            yy = 1900 + yy if yy >= 50 else 2000 + yy
        out[f"{yy:04d}-{MONTHS[mon.lower()]:02d}-{int(d):02d}"] = float(v)
    return out


def fed_fx(stems: tuple[str, ...]) -> dict[str, float]:
    out = {}
    for stem in stems:
        out.update(parse_fed(_get(FED_BASE + stem + ".htm").decode("utf-8", "ignore")))
    return out


def premium(adr: float, local: float, fx: float, ratio: float) -> float:
    if local <= 0 or fx <= 0:
        raise ValueError("share price and FX must be positive")
    return adr / (ratio * local / fx) - 1.0


def window_factor(date: str, windows: tuple[tuple[str, str, float], ...]) -> float:
    for start, end, f in windows:
        if start <= date < end:
            return f
    return 1.0


def build(adr: dict[str, float], local: dict[str, float], fx: dict[str, float], ratio: float,
          windows: tuple[tuple[str, str, float], ...] = ()) -> list[dict]:
    """Join on home-market trading dates that also had a US close; FX forward-filled to the date."""
    fx_dates = sorted(fx)
    rows = []
    for d in sorted(local):
        a = adr.get(d)
        if a is None:
            continue
        i = bisect.bisect_right(fx_dates, d) - 1
        if i < 0:
            continue
        f = fx[fx_dates[i]]
        a_adj = a * window_factor(d, windows)
        rows.append({"date": d, "adr": a_adj, "local": local[d], "fx": f, "premium": premium(a_adj, local[d], f, ratio)})
    return rows


def clean(rows: list[dict], fx_bounds: tuple[float, float], premium_bounds: tuple[float, float]) -> tuple[list[dict], list[dict]]:
    """(kept, dropped). Dropped rows are vendor errors, not market prints; callers show the count."""
    keep, drop = [], []
    for r in rows:
        ok = fx_bounds[0] <= r["fx"] <= fx_bounds[1] and premium_bounds[0] <= r["premium"] <= premium_bounds[1]
        (keep if ok else drop).append(r)
    return keep, drop


def fetch_case(case: Case) -> tuple[list[dict], list[dict]]:
    """(rows, dropped). Fed FX is authoritative; Yahoo FX only after the last weekly H.10 print."""
    adr, local = yahoo_daily(case.adr), yahoo_daily(case.local)
    fx: dict[str, float] = {}
    try:
        fx.update(fed_fx(case.fx_fed))
    except Exception:
        pass
    last_fed = max(fx) if fx else ""
    try:
        for d, v in yahoo_daily(case.fx_yahoo).items():
            if d > last_fed:
                fx[d] = v
    except Exception:
        pass
    if not fx:
        raise RuntimeError("no FX source reachable")
    return clean(build(adr, local, fx, case.ratio, case.adr_windows), case.fx_bounds, case.premium_bounds)


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "adr_usd", "local_px", "fx", "premium_pct"])
        for r in rows:
            w.writerow([r["date"], f"{r['adr']:.4f}", f"{r['local']:.4f}", f"{r['fx']:.4f}", f"{r['premium'] * 100:.3f}"])


def load_csv(path: Path) -> list[dict]:
    with path.open() as f:
        return [{"date": r["date"], "adr": float(r["adr_usd"]), "local": float(r["local_px"]), "fx": float(r["fx"]),
                 "premium": float(r["premium_pct"]) / 100} for r in csv.DictReader(f)]


def yearly(rows: list[dict]) -> list[dict]:
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(r["date"][:4], []).append(r["premium"])
    out = []
    for y, v in sorted(by.items()):
        s = sorted(v)
        out.append({"year": y, "mean": sum(v) / len(v), "median": s[len(s) // 2], "min": s[0], "max": s[-1], "days": len(v)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--case", choices=sorted(CASES), default="tsmc")
    ap.add_argument("--csv", type=Path)
    args = ap.parse_args(argv)
    case = CASES[args.case]
    rows, dropped = fetch_case(case)
    if not rows:
        print("no rows", file=sys.stderr)
        return 1
    out = args.csv or Path(f"data/{case.key}_premium.csv")
    write_csv(rows, out)
    print(f"{case.name}: {rows[0]['date']} -> {rows[-1]['date']}  n={len(rows)}  dropped={len(dropped)}  wrote {out}")
    for r in dropped:
        print(f"  dropped {r['date']}: adr {r['adr']:.2f} local {r['local']:.2f} fx {r['fx']:.4f} premium {r['premium'] * 100:+.1f}%")
    for y in yearly(rows):
        print(f"  {y['year']}  mean {y['mean'] * 100:+6.1f}%  median {y['median'] * 100:+6.1f}%  "
              f"min {y['min'] * 100:+6.1f}%  max {y['max'] * 100:+6.1f}%  days {y['days']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
