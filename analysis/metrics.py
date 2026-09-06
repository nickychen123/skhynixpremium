"""Derived live metrics for the SKHYNIX / SKHY pair. Pure functions, no I/O.

`derive()` takes the raw Hyperliquid asset contexts (string-valued dicts from
`metaAndAssetCtxs` or the `activeAssetCtx` stream), optional top-of-book dicts and
the USD/KRW oracle context, and returns every number the dashboard shows. All
ratios are fractions (0.36 = 36%); formatting is the caller's job.
"""
from __future__ import annotations

from typing import Any

RATIO = 10


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # drop NaN


def _pos(x: float | None) -> bool:
    return x is not None and x > 0


def parse_book(l2: dict[str, Any] | None) -> dict[str, float | None]:
    """Top of book from an l2Book response. Missing sides come back as None."""
    empty = {"bid": None, "bid_sz": None, "ask": None, "ask_sz": None}
    if not l2 or not l2.get("levels"):
        return empty
    bids, asks = (l2["levels"] + [[], []])[:2]
    bid = bids[0] if bids else None
    ask = asks[0] if asks else None
    return {
        "bid": _num(bid["px"]) if bid else None, "bid_sz": _num(bid["sz"]) if bid else None,
        "ask": _num(ask["px"]) if ask else None, "ask_sz": _num(ask["sz"]) if ask else None,
    }


def derive(ctx_a: dict[str, Any] | None, ctx_b: dict[str, Any] | None,
           book_a: dict[str, Any] | None = None, book_b: dict[str, Any] | None = None,
           ctx_krw: dict[str, Any] | None = None, ratio: int = RATIO) -> dict[str, float | None]:
    """A = common-share perp (xyz:SKHX), B = ADS perp (xyz:SKHY)."""
    def g(c: dict | None, k: str) -> float | None:
        return _num(c.get(k)) if c else None

    fields = {"mark": "markPx", "oracle": "oraclePx", "mid": "midPx", "prev": "prevDayPx",
              "fund": "funding", "oi": "openInterest", "vol": "dayNtlVlm", "hl_prem": "premium"}
    a = {k: g(ctx_a, src) for k, src in fields.items()}
    b = {k: g(ctx_b, src) for k, src in fields.items()}
    ba = book_a or parse_book(None)
    bb = book_b or parse_book(None)
    krw = g(ctx_krw, "oraclePx")

    def prem(adr: float | None, share: float | None) -> float | None:
        return adr * ratio / share - 1 if _pos(adr) and _pos(share) else None

    def rel(x: float | None, y: float | None) -> float | None:
        return x / y - 1 if _pos(x) and _pos(y) else None

    out: dict[str, float | None] = {}
    out.update({f"a_{k}": v for k, v in a.items()})
    out.update({f"b_{k}": v for k, v in b.items()})
    out.update({f"a_{k}": v for k, v in ba.items()})
    out.update({f"b_{k}": v for k, v in bb.items()})
    out["krw"] = krw

    out["mark_prem"] = prem(b["mark"], a["mark"])
    out["oracle_prem"] = prem(b["oracle"], a["oracle"])
    out["mid_prem"] = prem(b["mid"], a["mid"])
    out["sell_prem"] = prem(bb["bid"], ba["ask"])   # hit the ADS bid, lift the share ask
    out["buy_prem"] = prem(bb["ask"], ba["bid"])    # lift the ADS ask, hit the share bid
    out["dollar_prem"] = b["mark"] * ratio - a["mark"] if _pos(a["mark"]) and _pos(b["mark"]) else None
    out["a_basis"] = rel(a["mark"], a["oracle"])
    out["b_basis"] = rel(b["mark"], b["oracle"])
    out["a_apr"] = a["fund"] * 24 * 365 if a["fund"] is not None else None
    out["b_apr"] = b["fund"] * 24 * 365 if b["fund"] is not None else None
    carry = b["fund"] - a["fund"] if a["fund"] is not None and b["fund"] is not None else None
    out["carry_h"] = carry                       # long A / short B, per hour on notional
    out["carry_apr"] = carry * 24 * 365 if carry is not None else None
    out["krx_implied"] = a["oracle"] * krw if _pos(a["oracle"]) and _pos(krw) else None
    out["adr_implied"] = b["oracle"] * ratio * krw if _pos(b["oracle"]) and _pos(krw) else None
    mp = out["mark_prem"]
    out["unwind"] = 1 / (1 + mp) - 1 if mp is not None and mp > -1 else None
    out["a_chg"] = rel(a["mark"], a["prev"])
    out["b_chg"] = rel(b["mark"], b["prev"])
    out["a_spread_bps"] = (ba["ask"] / ba["bid"] - 1) * 1e4 if _pos(ba["bid"]) and _pos(ba["ask"]) else None
    out["b_spread_bps"] = (bb["ask"] / bb["bid"] - 1) * 1e4 if _pos(bb["bid"]) and _pos(bb["ask"]) else None
    out["a_oi_usd"] = a["oi"] * a["mark"] if a["oi"] is not None and _pos(a["mark"]) else None
    out["b_oi_usd"] = b["oi"] * b["mark"] if b["oi"] is not None and _pos(b["mark"]) else None
    return out
