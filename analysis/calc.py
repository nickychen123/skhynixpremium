"""Scenario calculator for the premium-compression trade. Pure functions, no I/O.

Position: long 1 share-equivalent of the common-share perp (A = SKHYNIX), short 10 ADS
perps (B = SKHY), i.e. one share-equivalent on each side. Everything is per one
share-equivalent; scale by the number of units for a real position.

Notation: S = common-share price (USD), p = ADR premium as a fraction, f_a / f_b =
hourly funding rates of the two perps as fractions (Hyperliquid convention: positive
means longs pay shorts), hours = holding period.

    price P&L   = S0*p0 - S1*p1             (the change in the dollar premium)
    funding P&L = hours * (f_b*V_b - f_a*V_a) with V the average leg notionals
    fees        = fee * (open notionals + close notionals)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    s0: float          # common-share price at entry, USD
    p0: float          # premium at entry, fraction
    s1: float          # common-share price at exit, USD
    p1: float          # premium at exit, fraction
    hours: float       # holding period
    f_a: float         # hourly funding, common-share perp (fraction)
    f_b: float         # hourly funding, ADS perp (fraction)
    fee: float = 0.0   # fee per leg per side, fraction of notional (0.0005 = 5 bps)
    ratio: int = 10


@dataclass(frozen=True)
class Result:
    price: float
    funding: float
    fees: float
    total: float
    notional_open: float     # both legs at entry, USD per share-equivalent
    v_a_open: float
    v_b_open: float

    def return_on_margin(self, leverage: float) -> float:
        """Total P&L over the margin posted for both legs at entry."""
        return self.total / (self.notional_open / leverage)

    def annualised(self, leverage: float, hours: float) -> float:
        return self.return_on_margin(leverage) * (8760.0 / hours) if hours > 0 else float("nan")


def evaluate(sc: Scenario) -> Result:
    v_a0, v_b0 = sc.s0, sc.s0 * (1 + sc.p0)
    v_a1, v_b1 = sc.s1, sc.s1 * (1 + sc.p1)
    price = sc.s0 * sc.p0 - sc.s1 * sc.p1
    v_a, v_b = (v_a0 + v_a1) / 2, (v_b0 + v_b1) / 2       # linear path assumption
    funding = sc.hours * (sc.f_b * v_b - sc.f_a * v_a)
    fees = sc.fee * (v_a0 + v_b0 + v_a1 + v_b1)
    return Result(price, funding, fees, price + funding - fees, v_a0 + v_b0, v_a0, v_b0)


def breakeven_exit_premium(sc: Scenario) -> float:
    """Exit premium p1 at which total P&L is zero, all else as in the scenario.

    total(p1) is linear in p1: price = s0*p0 - s1*p1; the B-leg average notional and the
    close fee both carry s1*(1+p1)/2 and s1*(1+p1) terms.
    """
    s0, s1, h = sc.s0, sc.s1, sc.hours
    const = (s0 * sc.p0
             + h * (sc.f_b * (s0 * (1 + sc.p0) + s1) / 2 - sc.f_a * (s0 + s1) / 2)
             - sc.fee * (s0 + s0 * (1 + sc.p0) + s1 + s1))
    coef = -s1 + h * sc.f_b * s1 / 2 - sc.fee * s1
    return -const / coef


def carry_apr(f_a: float, f_b: float, p: float = 0.0) -> float:
    """Annualised funding carry per unit of common-share notional, ADS leg weighted by (1+p)."""
    return (f_b * (1 + p) - f_a) * 24 * 365


def average_rate(entries: list[dict]) -> float | None:
    """Mean hourly funding rate from Hyperliquid fundingHistory rows."""
    vals = [float(e["fundingRate"]) for e in entries if "fundingRate" in e]
    return sum(vals) / len(vals) if vals else None


def grid(sc: Scenario, exit_premiums: list[float], holding_days: list[float], leverage: float) -> list[list[float]]:
    """Return-on-margin for each (exit premium, holding days) pair. Rows = premiums."""
    out = []
    for p1 in exit_premiums:
        row = []
        for d in holding_days:
            s = Scenario(sc.s0, sc.p0, sc.s1, p1, d * 24, sc.f_a, sc.f_b, sc.fee, sc.ratio)
            row.append(evaluate(s).return_on_margin(leverage))
        out.append(row)
    return out
