"""Minimal Hyperliquid info-API client (standard library only).

Kept dependency-free on purpose: the dashboard, the analysis scripts and the
tests all run on a bare Python install, which matters when you hand a tool to
someone on a locked-down desk machine.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

API = "https://api.hyperliquid.xyz/info"

SKHX = "xyz:SKHX"   # UI ticker SKHYNIX: one SK hynix common share (KRX 000660), in USD
SKHY = "xyz:SKHY"   # SK hynix ADR (Nasdaq: SKHY), in USD
KRW = "xyz:KRW"     # USD/KRW oracle
RATIO = 10          # ADSs per common share

INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


def info(body: dict[str, Any], timeout: int = 30) -> Any:
    """POST one request to the info endpoint and return the parsed JSON."""
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def candles(coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    """Candle snapshot. Each row: t (open time, ms), o/h/l/c/v as strings, n trades."""
    return info({"type": "candleSnapshot",
                 "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms}})


def funding_history(coin: str, start_ms: int, end_ms: int | None = None) -> list[dict[str, Any]]:
    """Hourly funding prints: time (ms), fundingRate (per hour, as a fraction), premium."""
    body: dict[str, Any] = {"type": "fundingHistory", "coin": coin, "startTime": start_ms}
    if end_ms is not None:
        body["endTime"] = end_ms
    return info(body)


def asset_ctx(dex: str = "xyz") -> dict[str, dict[str, Any]]:
    """Current context (mark, oracle, funding, OI...) for every asset on a HIP-3 dex, keyed by coin."""
    meta, ctxs = info({"type": "metaAndAssetCtxs", "dex": dex})
    return {u["name"]: ctx for u, ctx in zip(meta["universe"], ctxs)}


def now_ms() -> int:
    return int(time.time() * 1000)
