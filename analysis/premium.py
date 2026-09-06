"""ADR premium series: SK hynix ADS (xyz:SKHY) vs common share (xyz:SKHX).

    premium = (SKHY * 10) / SKHX - 1

Usage:
    python analysis/premium.py                      # 1d candles, full history, summary to stdout
    python analysis/premium.py --interval 1h --days 30 --csv data/premium_1h.csv

Pure functions (premium, unwind_move, align, stats) have no I/O and are unit-tested
in tests/test_premium.py. Network access happens only in main().
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hl  # noqa: E402


def premium(adr_px: float, share_px: float, ratio: int = hl.RATIO) -> float:
    """ADR premium as a fraction. 0.36 means the ADSs trade 36% above the share."""
    if share_px <= 0:
        raise ValueError("share price must be positive")
    return adr_px * ratio / share_px - 1.0


def unwind_move(p0: float, p1: float) -> float:
    """ADR price change if the premium goes from p0 to p1 with the home share flat.

    From 36% to parity: 1/1.36 - 1 = -26.5%, not -36%.
    """
    return (1.0 + p1) / (1.0 + p0) - 1.0


def align(share_candles: list[dict], adr_candles: list[dict], ratio: int = hl.RATIO) -> list[dict]:
    """Join two candle lists on open time and compute the premium from closes.

    Returns rows: {t, share, adr10, premium} with premium as a fraction.
    Candles missing on either side are dropped rather than forward-filled, so a
    gap in one market never manufactures a premium print.
    """
    adr = {c["t"]: float(c["c"]) for c in adr_candles}
    out = []
    for c in share_candles:
        b = adr.get(c["t"])
        a = float(c["c"])
        if b is None or a <= 0:
            continue
        out.append({"t": c["t"], "share": a, "adr10": b * ratio, "premium": premium(b, a, ratio)})
    return out


def stats(rows: list[dict], current: float | None = None) -> dict:
    """Range statistics on the premium column (fractions in, fractions out)."""
    vals = [r["premium"] for r in rows]
    if not vals:
        return {"n": 0}
    cur = vals[-1] if current is None else current
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else float("nan")
    below = sum(v <= cur for v in vals) / len(vals)
    return {
        "n": len(vals), "mean": mean, "sd": sd, "min": min(vals), "max": max(vals),
        "current": cur, "percentile": below,
        "z": (cur - mean) / sd if sd and not math.isnan(sd) and sd > 0 else float("nan"),
    }


def iso(t_ms: int) -> str:
    return datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def fetch(interval: str, days: int) -> list[dict]:
    end = hl.now_ms()
    start = end - days * 86_400_000
    return align(hl.candles(hl.SKHX, interval, start, end), hl.candles(hl.SKHY, interval, start, end))


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "t_ms", "skhx_usd", "skhy_x10_usd", "premium_pct"])
        for r in rows:
            w.writerow([iso(r["t"]), r["t"], f"{r['share']:.2f}", f"{r['adr10']:.2f}", f"{r['premium'] * 100:.3f}"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--interval", default="1d", choices=sorted(hl.INTERVAL_MS))
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--csv", type=Path, help="write the series to this CSV path")
    args = ap.parse_args(argv)

    rows = fetch(args.interval, args.days)
    if not rows:
        print("no overlapping candles returned", file=sys.stderr)
        return 1
    s = stats(rows)
    print(f"{hl.SKHY} x{hl.RATIO} vs {hl.SKHX}  interval={args.interval}  "
          f"{iso(rows[0]['t'])} -> {iso(rows[-1]['t'])}  n={s['n']}")
    print(f"premium  last {s['current'] * 100:+.2f}%  mean {s['mean'] * 100:+.2f}%  "
          f"sd {s['sd'] * 100:.2f}pp  min {s['min'] * 100:+.2f}%  max {s['max'] * 100:+.2f}%  "
          f"pct {s['percentile'] * 100:.0f}  z {s['z']:+.2f}")
    print("unwind from current premium, home share flat:")
    for target in (0.25, 0.20, 0.15, 0.10, 0.05, 0.0):
        print(f"   to {target * 100:4.0f}%  ->  ADR {unwind_move(s['current'], target) * 100:+.1f}%")
    if args.csv:
        write_csv(rows, args.csv)
        print(f"wrote {args.csv} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
