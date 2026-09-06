"""TSMC ADR premium history: TSM (NYSE, 1 ADS = 5 common shares) vs 2330.TW, in USD.

    premium = TSM / (5 * TW / USDTWD) - 1

Sources (all free, no keys):
  * Yahoo Finance chart API: daily closes for TSM (from the 1997-10-08 listing) and 2330.TW
    (from 2000-01-04). Yahoo's `close` is split-adjusted and both series carry the same
    stock-dividend events, so the 5:1 ratio holds throughout the adjusted series.
  * Federal Reserve H.10 historical files: USD/TWD noon buying rates, daily, from 1990.
    Yahoo's TWD=X only starts in 2004; the Fed series covers the gap.

Known gaps: no free daily source for 2330.TW before 2000, so the computed series starts
2000-01-04, about 27 months after the ADR listed. Reported figures for 1999-2000 are kept
in REPORTED so a chart can show them as labelled markers, not data.

Usage:  python analysis/tsmc.py --csv data/tsmc_premium.csv
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
from pathlib import Path

RATIO = 5
LISTED = "1997-10-08"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"}
FED_FILES = (
    "https://www.federalreserve.gov/releases/h10/hist/dat96_ta.htm",
    "https://www.federalreserve.gov/releases/h10/hist/dat00_ta.htm",
)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Reported, not computed. Sources: contemporary press via the research brief; The Economist (Jan 2000).
REPORTED = [
    ("1999-07-13", 31.75, "reported 12-month low"),
    ("2000-01-26", 115.0, "reported intraday high"),
    ("2000-01-28", 67.0, "reported close (Economist: about 70%)"),
]
EVENTS = [
    ("1999-05-11", "Board adopts ADS conversion-sale policy"),
    ("2000-06-15", "ADS offering priced about 43% above Taipei"),
    ("2003-10-02", "Taiwan abolishes the QFII system"),
]


def _get(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def yahoo_daily(symbol: str) -> dict[str, float]:
    """Split-adjusted daily closes keyed by ISO date (UTC date of the bar)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1=0&period2={int(time.time())}&interval=1d"
    res = json.loads(_get(url))["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    out = {}
    for t, c in zip(res["timestamp"], closes):
        if c is not None:
            out[time.strftime("%Y-%m-%d", time.gmtime(t))] = float(c)
    return out


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


def fed_twd() -> dict[str, float]:
    out = {}
    for url in FED_FILES:
        out.update(parse_fed(_get(url).decode("utf-8", "ignore")))
    return out


def premium(tsm: float, tw: float, fx: float, ratio: int = RATIO) -> float:
    if tw <= 0 or fx <= 0:
        raise ValueError("share price and FX must be positive")
    return tsm / (ratio * tw / fx) - 1.0


def build(tsm: dict[str, float], tw: dict[str, float], fx: dict[str, float]) -> list[dict]:
    """Join on Taiwan trading dates that also had a New York close; FX forward-filled to the date."""
    fx_dates = sorted(fx)
    rows = []
    for d in sorted(tw):
        a = tsm.get(d)
        if a is None:
            continue
        i = bisect.bisect_right(fx_dates, d) - 1
        if i < 0:
            continue
        f = fx[fx_dates[i]]
        rows.append({"date": d, "tsm": a, "tw": tw[d], "fx": f, "premium": premium(a, tw[d], f)})
    return rows


def clean(rows: list[dict], fx_lo: float = 20.0, fx_hi: float = 45.0,
          p_lo: float = -0.5, p_hi: float = 1.5) -> tuple[list[dict], list[dict]]:
    """Split rows into (kept, dropped). Dropped rows are vendor errors, not market prints:
    USD/TWD has traded between about 24 and 35 since 1990, and a premium outside -50%..+150%
    has never been reported. The count of dropped rows is shown wherever the series is used."""
    keep, drop = [], []
    for r in rows:
        (keep if fx_lo <= r["fx"] <= fx_hi and p_lo <= r["premium"] <= p_hi else drop).append(r)
    return keep, drop


def fetch_all() -> tuple[list[dict], list[dict]]:
    """Returns (rows, dropped). The Fed series is authoritative for FX; Yahoo's TWD=X is used
    only for dates after the last H.10 print (the release is weekly), because Yahoo's FX
    history carries occasional bad ticks."""
    tsm, tw = yahoo_daily("TSM"), yahoo_daily("2330.TW")
    fx: dict[str, float] = {}
    try:
        fx.update(fed_twd())
    except Exception:
        pass
    last_fed = max(fx) if fx else ""
    try:
        for d, v in yahoo_daily("TWD=X").items():
            if d > last_fed:
                fx[d] = v
    except Exception:
        pass
    if not fx:
        raise RuntimeError("no USD/TWD source reachable")
    return clean(build(tsm, tw, fx))


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "tsm_usd", "tw_twd", "usdtwd", "premium_pct"])
        for r in rows:
            w.writerow([r["date"], f"{r['tsm']:.4f}", f"{r['tw']:.4f}", f"{r['fx']:.4f}", f"{r['premium'] * 100:.3f}"])


def load_csv(path: Path) -> list[dict]:
    with path.open() as f:
        return [{"date": r["date"], "tsm": float(r["tsm_usd"]), "tw": float(r["tw_twd"]), "fx": float(r["usdtwd"]),
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
    ap.add_argument("--csv", type=Path, default=Path("data/tsmc_premium.csv"))
    args = ap.parse_args(argv)
    rows, dropped = fetch_all()
    if not rows:
        print("no rows", file=sys.stderr)
        return 1
    write_csv(rows, args.csv)
    print(f"{rows[0]['date']} -> {rows[-1]['date']}  n={len(rows)}  dropped={len(dropped)}  wrote {args.csv}")
    for r in dropped:
        print(f"  dropped {r['date']}: tsm {r['tsm']:.2f} tw {r['tw']:.2f} fx {r['fx']:.4f} premium {r['premium'] * 100:+.1f}%")
    for y in yearly(rows):
        print(f"  {y['year']}  mean {y['mean'] * 100:+6.1f}%  median {y['median'] * 100:+6.1f}%  "
              f"min {y['min'] * 100:+6.1f}%  max {y['max'] * 100:+6.1f}%  days {y['days']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
