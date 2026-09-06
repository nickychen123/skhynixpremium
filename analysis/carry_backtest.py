"""Backtest of the premium-compression trade on Hyperliquid perps.

Position: long 1 share-equivalent of xyz:SKHX, short 10 xyz:SKHY (one ADS-equivalent
share), held from --start to now, never rebalanced. Two P&L streams per hour:

    price   = -( d(SKHY*10) - d(SKHX) )          gains when the dollar premium narrows
    funding = ( f_SKHY - f_SKHX ) * notional       hourly funding, positive = position receives

Hyperliquid convention: a positive funding rate means longs pay shorts. The long
SKHX leg pays f_SKHX; the short SKHY leg receives f_SKHY. Each leg's funding is
charged on its own mark notional, approximated here by the hourly close.

Usage:
    python analysis/carry_backtest.py --start 2026-07-15 --csv data/carry_backtest.csv

The point of the exercise is not that the trade is good or bad; it is to separate
the two things people conflate when they call a 36% premium "free money": the
carry (which has been large and positive) and the path risk on the price leg
(which has been larger).
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hl  # noqa: E402
from premium import align, iso  # noqa: E402


def backtest(rows: list[dict], fund_a: dict[int, float], fund_b: dict[int, float]) -> list[dict]:
    """rows from align() at 1h; fund_* map hour-start ms -> hourly rate (fraction)."""
    out = []
    price_cum = fund_cum = 0.0
    peak = 0.0
    dd_max = 0.0
    prev = rows[0]
    for r in rows:
        d_price = -((r["adr10"] - prev["adr10"]) - (r["share"] - prev["share"]))
        fa = fund_a.get(r["t"], 0.0)
        fb = fund_b.get(r["t"], 0.0)
        d_fund = fb * r["adr10"] - fa * r["share"]
        price_cum += d_price
        fund_cum += d_fund
        total = price_cum + fund_cum
        peak = max(peak, total)
        dd_max = max(dd_max, peak - total)
        out.append({"t": r["t"], "share": r["share"], "adr10": r["adr10"], "premium": r["premium"],
                    "f_skhx": fa, "f_skhy": fb, "price_pnl": price_cum, "funding_pnl": fund_cum,
                    "total_pnl": total, "drawdown": peak - total})
        prev = r
    return out


def summarize(bt: list[dict]) -> dict:
    first, last = bt[0], bt[-1]
    hours = max(1, len(bt) - 1)
    notional0 = first["share"]
    return {
        "start": iso(first["t"]), "end": iso(last["t"]), "hours": hours,
        "entry_premium": first["premium"], "exit_premium": last["premium"],
        "notional_usd": notional0,
        "price_pnl": last["price_pnl"], "funding_pnl": last["funding_pnl"], "total_pnl": last["total_pnl"],
        "price_pct": last["price_pnl"] / notional0, "funding_pct": last["funding_pnl"] / notional0,
        "total_pct": last["total_pnl"] / notional0,
        "funding_apr": last["funding_pnl"] / notional0 / hours * 24 * 365,
        "max_drawdown_usd": max(r["drawdown"] for r in bt),
        "max_drawdown_pct": max(r["drawdown"] for r in bt) / notional0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default="2026-07-15", help="UTC date, YYYY-MM-DD")
    ap.add_argument("--csv", type=Path)
    args = ap.parse_args(argv)

    start = int(datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end = hl.now_ms()
    rows = align(hl.candles(hl.SKHX, "1h", start, end), hl.candles(hl.SKHY, "1h", start, end))
    if len(rows) < 2:
        print("not enough hourly candles", file=sys.stderr)
        return 1
    fa = {f["time"] // 3_600_000 * 3_600_000: float(f["fundingRate"]) for f in hl.funding_history(hl.SKHX, start, end)}
    fb = {f["time"] // 3_600_000 * 3_600_000: float(f["fundingRate"]) for f in hl.funding_history(hl.SKHY, start, end)}
    bt = backtest(rows, fa, fb)
    s = summarize(bt)

    print(f"long 1x {hl.SKHX} / short 10x {hl.SKHY}   {s['start']} -> {s['end']}   {s['hours']} hours")
    print(f"entry premium {s['entry_premium'] * 100:+.1f}%   exit premium {s['exit_premium'] * 100:+.1f}%   "
          f"long-leg notional at entry ${s['notional_usd']:,.0f}")
    print(f"price P&L    {s['price_pnl']:+9.1f} USD  ({s['price_pct'] * 100:+.1f}% of notional)")
    print(f"funding P&L  {s['funding_pnl']:+9.1f} USD  ({s['funding_pct'] * 100:+.1f}% of notional, "
          f"{s['funding_apr'] * 100:+.0f}% APR)")
    print(f"total P&L    {s['total_pnl']:+9.1f} USD  ({s['total_pct'] * 100:+.1f}%)")
    print(f"max drawdown {s['max_drawdown_usd']:9.1f} USD  ({s['max_drawdown_pct'] * 100:.1f}%)")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(bt[0].keys()))
            w.writeheader()
            for r in bt:
                w.writerow({k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in r.items()})
        print(f"wrote {args.csv} ({len(bt)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
