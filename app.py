"""SKHYNIX / SKHY premium monitor, Streamlit edition.

    streamlit run app.py

Reuses the tested analysis layer in analysis/: hl (API client), metrics (derived
live numbers), premium (series and stats), market_hours (venue sessions) and
carry_backtest. Live data is polled over REST inside auto-refreshing fragments;
history and backtests are cached.
"""
from __future__ import annotations

import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
import hl  # noqa: E402
import market_hours as mh  # noqa: E402
import metrics  # noqa: E402
import tsmc  # noqa: E402
from calc import Scenario, average_rate, breakeven_exit_premium, carry_apr, evaluate, grid  # noqa: E402
from carry_backtest import backtest, summarize  # noqa: E402
from premium import align, stats, unwind_move  # noqa: E402

st.set_page_config(page_title="SKHYNIX / SKHY premium", page_icon="📐", layout="wide")

C_PREM, C_KR, C_ADR, C_WARN, C_MUTED = "#9085e9", "#3987e5", "#d95926", "#e0a35a", "#8a8598"
RANGES = {"24H": ("5m", 1), "7D": ("30m", 7), "30D": ("1h", 30), "All": ("4h", 400)}
LISTING = date(2026, 7, 9)


# ---------------------------------------------------------------- formatting
def ok(x) -> bool:
    return x is not None and x == x


def pct(x, d=2, sign=True, scale=100.0) -> str:
    if not ok(x):
        return "—"
    v = x * scale
    return f"{v:+.{d}f}%" if sign else f"{v:.{d}f}%"


def usd(x, d=2) -> str:
    if not ok(x):
        return "—"
    return f"{'−' if x < 0 else ''}${abs(x):,.{d}f}"


def md(s: str) -> str:
    """Escape dollar signs so Streamlit's markdown does not read them as LaTeX delimiters."""
    return s.replace("$", "\\$")


TILE_CSS = """<style>
.tile{padding:2px 0 6px}
.tile-label{font-size:.82rem;opacity:.75;margin-bottom:2px}
.tile-value{font-size:1.55rem;font-weight:600;line-height:1.2;overflow-wrap:anywhere}
.tile-sub{font-size:1rem;font-weight:500;line-height:1.3;margin-top:2px}
.tile-cap{font-size:.78rem;opacity:.6;line-height:1.35;margin-top:4px}
</style>"""


def tile(col, label: str, value: str, sub: str | None = None, caption: str | None = None, help: str | None = None) -> None:
    """A metric tile that wraps long values instead of truncating them (st.metric cuts them off)."""
    title = f' title="{help}"' if help else ""
    parts = [f'<div class="tile"><div class="tile-label"{title}>{label}{" ⓘ" if help else ""}</div>',
             f'<div class="tile-value">{value}</div>']
    if sub:
        parts.append(f'<div class="tile-sub">{sub}</div>')
    if caption:
        parts.append(f'<div class="tile-cap">{caption}</div>')
    parts.append("</div>")
    col.markdown("".join(parts), unsafe_allow_html=True)   # raw HTML: no markdown/LaTeX processing, so no escaping


st.markdown(TILE_CSS, unsafe_allow_html=True)


def krw(x) -> str:
    return f"₩{x:,.0f}" if ok(x) else "—"


def compact(x) -> str:
    if not ok(x):
        return "—"
    a = abs(x)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{x / div:,.1f}{suf}"
    return f"{x:,.0f}"


def age(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def utc_clock() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


# ---------------------------------------------------------------- data
@st.cache_data(ttl=60, show_spinner=False)
def load_history(range_key: str):
    interval, days = RANGES[range_key]
    end = hl.now_ms()
    start = end - days * 86_400_000
    rows = align(hl.candles(hl.SKHX, interval, start, end), hl.candles(hl.SKHY, interval, start, end))
    df = pd.DataFrame(rows)
    if not df.empty:
        df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        df["premium_pct"] = df["premium"] * 100
    fa = pd.DataFrame(hl.funding_history(hl.SKHX, start, end))
    fb = pd.DataFrame(hl.funding_history(hl.SKHY, start, end))
    fdf = pd.DataFrame(columns=["time", "skhx_apr", "skhy_apr"])
    if not fa.empty and not fb.empty:
        for f in (fa, fb):
            f["hour"] = f["time"] // 3_600_000 * 3_600_000
            f["apr"] = f["fundingRate"].astype(float) * 24 * 365 * 100
        fdf = fa[["hour", "apr"]].merge(fb[["hour", "apr"]], on="hour", how="outer", suffixes=("_a", "_b")).sort_values("hour")
        fdf = fdf.rename(columns={"apr_a": "skhx_apr", "apr_b": "skhy_apr"})
        fdf["time"] = pd.to_datetime(fdf["hour"], unit="ms", utc=True)
        fdf["carry_apr"] = fdf["skhy_apr"] - fdf["skhx_apr"]
    return df, fdf, interval


@st.cache_data(ttl=300, show_spinner=False)
def load_baselines():
    end = hl.now_ms()
    h = align(hl.candles(hl.SKHX, "1h", end - 25 * 3_600_000, end), hl.candles(hl.SKHY, "1h", end - 25 * 3_600_000, end))
    d = align(hl.candles(hl.SKHX, "1d", end - 31 * 86_400_000, end), hl.candles(hl.SKHY, "1d", end - 31 * 86_400_000, end))
    p30 = [r["premium"] for r in d]
    return {
        "p24": h[0]["premium"] if h else None,
        "spark": pd.DataFrame(h),
        "mean30": sum(p30) / len(p30) if p30 else None,
        "min30": min(p30) if p30 else None,
        "max30": max(p30) if p30 else None,
    }


@st.cache_data(ttl=300, show_spinner=False)
def load_backtest(start_iso: str):
    start = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end = hl.now_ms()
    rows = align(hl.candles(hl.SKHX, "1h", start, end), hl.candles(hl.SKHY, "1h", start, end))
    if len(rows) < 2:
        return pd.DataFrame(), None
    fa = {f["time"] // 3_600_000 * 3_600_000: float(f["fundingRate"]) for f in hl.funding_history(hl.SKHX, start, end)}
    fb = {f["time"] // 3_600_000 * 3_600_000: float(f["fundingRate"]) for f in hl.funding_history(hl.SKHY, start, end)}
    bt = backtest(rows, fa, fb)
    df = pd.DataFrame(bt)
    df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df, summarize(bt)


def fetch_live() -> dict:
    ctx = hl.asset_ctx("xyz")
    ba, bb = hl.l2_book(hl.SKHX), hl.l2_book(hl.SKHY)
    return metrics.derive(ctx.get(hl.SKHX), ctx.get(hl.SKHY), metrics.parse_book(ba), metrics.parse_book(bb), ctx.get(hl.KRW))


# ---------------------------------------------------------------- charts
def base_layout(fig: go.Figure, height: int, ysuffix: str = "", ytickformat: str | None = None) -> go.Figure:
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(gridcolor="#2b2736", zeroline=False, ticksuffix=ysuffix, tickformat=ytickformat),
        font=dict(family="system-ui, Segoe UI, sans-serif", size=12, color="#b7b2c5"),
    )
    return fig


def premium_chart(df: pd.DataFrame, thresholds: list[tuple[float, str]], live: tuple | None) -> go.Figure:
    fig = go.Figure()
    x, y = df["time"], df["premium_pct"]
    if live:
        x = pd.concat([x, pd.Series([live[0]])], ignore_index=True)
        y = pd.concat([y, pd.Series([live[1]])], ignore_index=True)
    floor = min(y.min(), min([t[0] for t in thresholds], default=y.min())) - 1.5
    fig.add_trace(go.Scatter(x=x, y=[floor] * len(x), mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name="ADR premium", line=dict(color=C_PREM, width=2),
                             fill="tonexty", fillcolor="rgba(144,133,233,0.10)", hovertemplate="%{y:+.2f}%<extra>premium</extra>"))
    fig.add_trace(go.Scatter(x=[x.iloc[-1]], y=[y.iloc[-1]], mode="markers+text", text=[f"{y.iloc[-1]:+.2f}%"],
                             textposition="middle right", marker=dict(color=C_PREM, size=9, line=dict(color="#1a1722", width=2)),
                             showlegend=False, hoverinfo="skip"))
    for v, label in thresholds:
        fig.add_hline(y=v, line_dash="dash", line_color=C_WARN, line_width=1, annotation_text=label, annotation_position="top left")
    base_layout(fig, 340, ysuffix="%")
    fig.update_yaxes(range=[floor, y.max() + 1.5])
    fig.update_layout(showlegend=False)
    return fig


def two_line_chart(df: pd.DataFrame, cols: tuple[str, str], names: tuple[str, str], colors: tuple[str, str],
                   ysuffix: str = "", yprefix: str = "", height: int = 280, hover: str = "%{y:,.1f}") -> go.Figure:
    fig = go.Figure()
    for c, n, col in zip(cols, names, colors):
        fig.add_trace(go.Scatter(x=df["time"], y=df[c], mode="lines", name=n, line=dict(color=col, width=2),
                                 hovertemplate=yprefix + hover + ysuffix + "<extra>" + n + "</extra>"))
    base_layout(fig, height, ysuffix=ysuffix)
    fig.update_yaxes(tickprefix=yprefix)
    return fig


def sparkline(df: pd.DataFrame, live_prem: float | None) -> go.Figure:
    fig = go.Figure()
    if not df.empty:
        x = pd.to_datetime(df["t"], unit="ms", utc=True)
        y = df["premium"] * 100
        if ok(live_prem):
            x = pd.concat([x, pd.Series([pd.Timestamp.now(tz="UTC")])], ignore_index=True)
            y = pd.concat([y, pd.Series([live_prem * 100])], ignore_index=True)
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=C_MUTED, width=2), hovertemplate="%{y:+.2f}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=[x.iloc[-1]], y=[y.iloc[-1]], mode="markers", marker=dict(color=C_PREM, size=8), hoverinfo="skip"))
    fig.update_layout(template="plotly_dark", height=110, margin=dict(l=0, r=0, t=4, b=0), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### Settings")
    range_key = st.radio("History range", list(RANGES), index=2, horizontal=True)
    refresh = st.slider("Live refresh (seconds)", 2, 15, 4)
    st.markdown("### Alerts on mark premium")
    al_upper = st.number_input("Above (%)", value=None, step=0.5, placeholder="e.g. 40")
    al_lower = st.number_input("Below (%)", value=None, step=0.5, placeholder="e.g. 30")
    al_z = st.checkbox("|z| ≥ 2 vs selected range", help="Fires when the mark premium is two standard deviations from the range mean; re-arms inside 1.5.")
    if st.button("Clear alert log"):
        st.session_state["alert_log"] = []
    st.markdown("---")
    st.caption("Data: Hyperliquid public API, REST polling. `xyz:SKHX` = SKHYNIX, one KRX common share in USD. "
               "`xyz:SKHY` = SK hynix ADS. 10 ADSs = 1 share. Sessions ignore holidays. Not investment advice.")

st.session_state.setdefault("alert_log", [])
st.session_state.setdefault("armed", {"upper": True, "lower": True, "z": True})
st.session_state.setdefault("oracle_track", {})
st.session_state.setdefault("last_z", None)


# ---------------------------------------------------------------- alerts
def check_alerts(d: dict) -> None:
    p = d.get("mark_prem")
    if not ok(p):
        return
    p *= 100
    armed, log = st.session_state["armed"], st.session_state["alert_log"]

    def fire(msg: str) -> None:
        line = f"{datetime.now():%H:%M:%S}  {msg} · now {p:+.2f}%"
        log.insert(0, line)
        del log[50:]
        st.toast(msg, icon="⚠️")

    if al_upper is not None:
        if not armed["upper"] and p < al_upper - 0.1:
            armed["upper"] = True
        elif armed["upper"] and p >= al_upper:
            armed["upper"] = False
            fire(f"Premium above {al_upper:+.1f}%")
    if al_lower is not None:
        if not armed["lower"] and p > al_lower + 0.1:
            armed["lower"] = True
        elif armed["lower"] and p <= al_lower:
            armed["lower"] = False
            fire(f"Premium below {al_lower:+.1f}%")
    z = st.session_state.get("last_z")
    if al_z and ok(z):
        if not armed["z"] and abs(z) < 1.5:
            armed["z"] = True
        elif armed["z"] and abs(z) >= 2:
            armed["z"] = False
            fire(f"Premium z-score {z:+.2f} vs {range_key}")


# ---------------------------------------------------------------- header
st.title("SKHYNIX / SKHY premium")
st.caption("Hyperliquid HIP-3 (XYZ) · `xyz:SKHX` SK hynix common share vs `xyz:SKHY` SK hynix ADS · 10 ADSs = 1 share · "
           "premium = SKHY × 10 / SKHYNIX − 1")

tab_live, tab_bt, tab_trade, tab_calc, tab_tsmc, tab_about = st.tabs(
    ["Monitor", "Carry backtest", "Trade calculator", "Unwind calculator", "TSMC since 2000", "About"])


# ---------------------------------------------------------------- live panel
@st.fragment(run_every=refresh)
def live_panel() -> None:
    err = None
    try:
        d = fetch_live()
        st.session_state["last_good"] = d
        st.session_state["last_fetch"] = time.time()
    except Exception as e:  # network or API failure: keep showing the last good values
        d, err = st.session_state.get("last_good"), str(e)
    if err:
        st.warning(f"Live feed error: {err}. Showing the last good values.")
    if not d:
        st.info("Waiting for the first live update…")
        return
    try:
        base = load_baselines()
    except Exception:
        base = {"p24": None, "spark": pd.DataFrame(), "mean30": None, "min30": None, "max30": None}

    track = st.session_state["oracle_track"]
    for coin, px in ((hl.SKHX, d["a_oracle"]), (hl.SKHY, d["b_oracle"])):
        if coin not in track or track[coin][0] != px:
            track[coin] = (px, time.time())
    check_alerts(d)

    # hero
    h1, h2 = st.columns([3, 2])
    with h1:
        delta = f"{(d['mark_prem'] - base['p24']) * 100:+.2f} pp vs 24h ago" if ok(d["mark_prem"]) and ok(base["p24"]) else None
        st.metric("ADR premium · SKHY mark × 10 vs SKHYNIX mark", pct(d["mark_prem"]), delta=delta, delta_color="off")
        st.caption(md(f"SKHY {usd(d['b_mark'])} × 10 = {usd(d['b_mark'] * 10 if ok(d['b_mark']) else None)}  vs  "
                      f"SKHYNIX {usd(d['a_mark'])}  ·  {usd(d['dollar_prem'])} per common share  ·  "
                      f"unwind to parity {pct(d['unwind'], 1)}"))
        if ok(base["mean30"]):
            st.caption(f"vs 30-day mean {(d['mark_prem'] - base['mean30']) * 100:+.2f} pp (mean {pct(base['mean30'], 1)})  ·  "
                       f"30-day range {pct(base['min30'], 1)} to {pct(base['max30'], 1)}")
    with h2:
        st.plotly_chart(sparkline(base["spark"], d["mark_prem"]), width="stretch", config={"displayModeBar": False}, key="spark")
        st.caption("last 24h, hourly")

    # tiles
    k = mh.session_state(mh.KRX)
    n = mh.session_state(mh.NASDAQ)
    now = time.time()
    oa = now - track[hl.SKHX][1] if hl.SKHX in track else None
    ob = now - track[hl.SKHY][1] if hl.SKHY in track else None
    t = st.columns(6)
    tile(t[0], "Oracle premium", pct(d["oracle_prem"]),
         caption=f"SKHY {usd(d['b_oracle'])} · SKHYNIX {usd(d['a_oracle'], 1)} · oracles last moved {age(oa)} / {age(ob)} ago",
         help="SKHY oracle × 10 / SKHYNIX oracle − 1. Oracles only move while the underlying venue trades.")
    tile(t[1], "Executable · sell premium", pct(d["sell_prem"]), sub=f"buy {pct(d['buy_prem'])}",
         caption=f"SKHYNIX {d['a_bid'] or '—'} / {d['a_ask'] or '—'} · SKHY {d['b_bid'] or '—'} / {d['b_ask'] or '—'}",
         help="Sell premium: hit the SKHY bid, lift the SKHYNIX ask. Buy premium: the reverse.")
    tile(t[2], "Carry · long SKHYNIX / short SKHY", f"{pct(d['carry_apr'], 1)} APR", sub=f"net {pct(d['carry_h'], 4)}/h",
         caption=f"SKHYNIX {pct(d['a_fund'], 4)}/h ({pct(d['a_apr'], 0)}) · SKHY {pct(d['b_fund'], 4)}/h ({pct(d['b_apr'], 0)})",
         help="SKHY funding − SKHYNIX funding, hourly, annualised. Positive = the position receives.")
    tile(t[3], "Implied KRX price", krw(d["krx_implied"]),
         caption=(f"USD/KRW {d['krw']:,.1f} · ADR-implied {krw(d['adr_implied'])}" if ok(d["krw"]) else "USD/KRW oracle unavailable"),
         help="SKHYNIX oracle × USD/KRW oracle")
    tile(t[4], "KRX session", "Open" if k.is_open else "Closed", sub=("closes in " if k.is_open else "opens in ") + k.until_label,
         caption=f"{k.local:%H:%M} KST · {mh.KRX.hours_label}")
    tile(t[5], "Nasdaq session", "Open" if n.is_open else "Closed", sub=("closes in " if n.is_open else "opens in ") + n.until_label,
         caption=f"{n.local:%H:%M} ET · {mh.NASDAQ.hours_label}")

    fetched = st.session_state.get("last_fetch")
    st.caption(f"REST polling every {refresh}s · last update {age(now - fetched) if fetched else '—'} ago · {utc_clock()}")

    # market details + alerts
    m1, m2 = st.columns([3, 2])
    with m1:
        rows = [
            ("Mark", usd(d["a_mark"], 1), usd(d["b_mark"] * 10, 1) if ok(d["b_mark"]) else "—", usd(d["b_mark"])),
            ("Oracle", usd(d["a_oracle"], 1), usd(d["b_oracle"] * 10, 1) if ok(d["b_oracle"]) else "—", usd(d["b_oracle"])),
            ("Mid", usd(d["a_mid"]), usd(d["b_mid"] * 10) if ok(d["b_mid"]) else "—", usd(d["b_mid"], 3)),
            ("Spread (bps)", f"{d['a_spread_bps']:.1f}" if ok(d["a_spread_bps"]) else "—", f"{d['b_spread_bps']:.1f}" if ok(d["b_spread_bps"]) else "—", ""),
            ("Mark vs oracle", pct(d["a_basis"], 3), pct(d["b_basis"], 3), ""),
            ("HL premium (impact vs oracle)", pct(d["a_hl_prem"], 3), pct(d["b_hl_prem"], 3), ""),
            ("Funding, hourly", pct(d["a_fund"], 4), pct(d["b_fund"], 4), ""),
            ("Funding, annualised", pct(d["a_apr"], 1), pct(d["b_apr"], 1), ""),
            ("Open interest", f"{compact(d['a_oi'])} sh · ${compact(d['a_oi_usd'])}", "", f"{compact(d['b_oi'])} ADS · ${compact(d['b_oi_usd'])}"),
            ("24h volume", f"${compact(d['a_vol'])}", "", f"${compact(d['b_vol'])}"),
            ("24h change (mark)", pct(d["a_chg"]), "", pct(d["b_chg"])),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["", "SKHYNIX", "SKHY ×10", "SKHY per ADS"]), hide_index=True, width="stretch")
    with m2:
        st.markdown("**Alerts**")
        parts = []
        if al_upper is not None:
            parts.append(f"above {al_upper:+.1f}% ({'armed' if st.session_state['armed']['upper'] else 'triggered'})")
        if al_lower is not None:
            parts.append(f"below {al_lower:+.1f}% ({'armed' if st.session_state['armed']['lower'] else 'triggered'})")
        if al_z:
            z = st.session_state.get("last_z")
            parts.append(f"|z| ≥ 2 vs {range_key} (now {z:+.2f})" if ok(z) else "|z| ≥ 2 (waiting for history)")
        st.caption("Watching mark premium " + " and ".join(parts) + "." if parts else "No thresholds set. Use the sidebar.")
        log = st.session_state["alert_log"]
        if log:
            st.code("\n".join(log), language=None)
        else:
            st.caption("No alerts yet.")


# ---------------------------------------------------------------- history panel
@st.fragment(run_every=60)
def history_panel() -> None:
    try:
        df, fdf, interval = load_history(range_key)
    except Exception as e:
        st.error(f"History load failed: {e}")
        return
    if df.empty:
        st.info("No candles returned for this range.")
        return
    live = st.session_state.get("last_good")
    live_pt = (pd.Timestamp.now(tz="UTC"), live["mark_prem"] * 100) if live and ok(live.get("mark_prem")) else None
    cur = live["mark_prem"] if live and ok(live.get("mark_prem")) else None
    s = stats([{"premium": p} for p in df["premium"]], current=cur)
    st.session_state["last_z"] = s.get("z") if ok(s.get("z")) else None

    st.markdown(f"**ADR premium, %** · {range_key} · {interval} candles · updated {utc_clock()}")
    c = st.columns(7)
    for col, (label, val) in zip(c, [("min", pct(s["min"])), ("max", pct(s["max"])), ("mean", pct(s["mean"])),
                                     ("std dev", f"{s['sd'] * 100:.2f} pp"), ("percentile", f"{s['percentile'] * 100:.0f}%"),
                                     ("z-score", f"{s['z']:+.2f}" if ok(s["z"]) else "—"), ("points", str(s["n"]))]):
        col.metric(label, val)
    th = []
    if al_upper is not None:
        th.append((al_upper, f"alert {al_upper:+.1f}%"))
    if al_lower is not None:
        th.append((al_lower, f"alert {al_lower:+.1f}%"))
    st.plotly_chart(premium_chart(df, th, live_pt), width="stretch", key="prem_chart")

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Price per common share, USD**")
        st.plotly_chart(two_line_chart(df, ("share", "adr10"), ("SKHYNIX", "SKHY ×10"), (C_KR, C_ADR), yprefix="$"),
                        width="stretch", key="px_chart")
    with g2:
        st.markdown("**Funding rate, annualised %**")
        if fdf.empty:
            st.info("No funding prints in range.")
        else:
            st.plotly_chart(two_line_chart(fdf, ("skhx_apr", "skhy_apr"), ("SKHYNIX", "SKHY"), (C_KR, C_ADR), ysuffix="%", hover="%{y:+,.0f}"),
                            width="stretch", key="fund_chart")
    out = df[["time", "share", "adr10", "premium_pct"]].rename(columns={"time": "time_utc", "share": "skhx_usd", "adr10": "skhy_x10_usd"})
    st.download_button("Download CSV", out.to_csv(index=False).encode(), file_name=f"skhy_premium_{range_key}_{interval}.csv",
                       mime="text/csv", key="dl_hist")
    with st.expander("Data table"):
        st.dataframe(out.iloc[::-1], hide_index=True, width="stretch", height=300)


with tab_live:
    live_panel()
    st.markdown("---")
    history_panel()


# ---------------------------------------------------------------- backtest tab
with tab_bt:
    st.markdown("**Long 1 SKHYNIX / short 10 SKHY, held from the start date, never rebalanced.** "
                "Price P&L gains when the dollar premium narrows; funding P&L = (f_SKHY − f_SKHX) × notional each hour, "
                "using the exchange's actual hourly prints. Both legs are charged on their own mark notional.")
    start = st.date_input("Start (UTC)", value=date(2026, 7, 15), min_value=LISTING, max_value=date.today())
    try:
        bdf, bs = load_backtest(start.isoformat())
    except Exception as e:
        bdf, bs = pd.DataFrame(), None
        st.error(f"Backtest data failed: {e}")
    if bs:
        b = st.columns(6)
        b[0].metric("Entry premium", pct(bs["entry_premium"], 1))
        b[1].metric("Exit premium", pct(bs["exit_premium"], 1))
        b[2].metric("Price P&L", pct(bs["price_pct"], 1), help=f"{bs['price_pnl']:+,.1f} USD on {bs['notional_usd']:,.0f} USD long-leg notional")
        b[3].metric("Funding P&L", pct(bs["funding_pct"], 1), delta=f"{bs['funding_apr'] * 100:+.0f}% APR", delta_color="off")
        b[4].metric("Total P&L", pct(bs["total_pct"], 1))
        b[5].metric("Max drawdown", pct(bs["max_drawdown_pct"], 1, sign=False))
        fig = go.Figure()
        for col, name, color in (("price_pnl", "price", C_KR), ("funding_pnl", "funding", C_ADR), ("total_pnl", "total", C_PREM)):
            fig.add_trace(go.Scatter(x=bdf["time"], y=bdf[col], mode="lines", name=name, line=dict(color=color, width=2),
                                     hovertemplate="%{y:+,.1f} USD<extra>" + name + "</extra>"))
        fig.add_trace(go.Scatter(x=bdf["time"], y=-bdf["drawdown"], mode="lines", name="drawdown", line=dict(color=C_WARN, width=1),
                                 fill="tozeroy", fillcolor="rgba(224,163,90,0.10)", hovertemplate="%{y:,.1f} USD<extra>drawdown</extra>"))
        base_layout(fig, 360, ysuffix=" USD")
        st.plotly_chart(fig, width="stretch", key="bt_chart")
        st.caption(md(f"{bs['start']} → {bs['end']} · {bs['hours']} hours · long-leg notional at entry {usd(bs['notional_usd'], 0)}. "
                      "The carry tile is a snapshot; this is the realised path. They disagree by design."))
        st.download_button("Download backtest CSV", bdf.drop(columns=["time"]).to_csv(index=False).encode(),
                           file_name=f"carry_backtest_{start.isoformat()}.csv", mime="text/csv", key="dl_bt")


# ---------------------------------------------------------------- trade calculator tab
@st.cache_data(ttl=300, show_spinner=False)
def load_funding_window(start_ms: int, end_ms: int):
    return hl.funding_history(hl.SKHX, start_ms, end_ms), hl.funding_history(hl.SKHY, start_ms, end_ms)


def funding_summary(entries: list[dict]) -> dict:
    vals = sorted(float(e["fundingRate"]) for e in entries)
    if not vals:
        return {"n": 0}
    n = len(vals)
    mean = sum(vals) / n
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    return {"n": n, "mean": mean, "median": med, "min": vals[0], "max": vals[-1],
            "share_positive": sum(v > 0 for v in vals) / n}


with tab_trade:
    live = st.session_state.get("last_good") or {}
    st.markdown("**What does long 1 SKHYNIX / short 10 SKHY earn if the premium goes from here to there, "
                "over a given holding period, at a given funding rate?** Price P&L is the change in the dollar premium "
                "(S₀·p₀ − S₁·p₁). Funding accrues hourly on each leg's notional. Fees are charged on open and close.")

    st.markdown("##### 1 · Funding assumptions")
    f1, f2 = st.columns([1, 2])
    with f1:
        window = st.radio("Average funding over", ["Last 24h", "Last 7d", "Last 30d", "Since listing", "Custom"], index=1)
        if window == "Custom":
            c_from, c_to = st.date_input("From", value=date(2026, 8, 1), min_value=LISTING, key="fw_from"), \
                           st.date_input("To", value=date.today(), min_value=LISTING, key="fw_to")
            w_start = int(datetime.combine(c_from, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
            w_end = int(datetime.combine(c_to, datetime.max.time(), tzinfo=timezone.utc).timestamp() * 1000)
        else:
            days = {"Last 24h": 1, "Last 7d": 7, "Last 30d": 30, "Since listing": 400}[window]
            w_end = hl.now_ms()
            w_start = w_end - days * 86_400_000
    with f2:
        try:
            fa_hist, fb_hist = load_funding_window(w_start, w_end)
            sa, sb = funding_summary(fa_hist), funding_summary(fb_hist)
        except Exception as e:
            sa = sb = {"n": 0}
            st.error(f"Funding history failed: {e}")
        if sa["n"] and sb["n"]:
            rows = [("Mean hourly", pct(sa["mean"], 4), pct(sb["mean"], 4), pct(sb["mean"] - sa["mean"], 4)),
                    ("Median hourly", pct(sa["median"], 4), pct(sb["median"], 4), pct(sb["median"] - sa["median"], 4)),
                    ("Annualised (mean × 8760)", pct(sa["mean"] * 8760, 0), pct(sb["mean"] * 8760, 0), pct((sb["mean"] - sa["mean"]) * 8760, 0)),
                    ("Hours with positive rate", f"{sa['share_positive'] * 100:.0f}%", f"{sb['share_positive'] * 100:.0f}%", ""),
                    ("Prints", str(sa["n"]), str(sb["n"]), "")]
            st.dataframe(pd.DataFrame(rows, columns=["", "SKHYNIX", "SKHY", "net carry (SKHY − SKHYNIX)"]), hide_index=True, width="stretch")
            if st.button("Use these averages in the scenario", key="use_avg"):
                st.session_state["tc_fa"] = round(sa["mean"] * 100, 5)
                st.session_state["tc_fb"] = round(sb["mean"] * 100, 5)
                st.rerun()
            st.caption("Net carry is what the position receives per hour per unit of notional when positive. "
                       "Averages over a window are an assumption about the future, not a forecast.")

    st.markdown("##### 2 · Scenario")
    s_a = live.get("a_mark") if ok(live.get("a_mark")) else 1250.0
    p_now = live.get("mark_prem") * 100 if ok(live.get("mark_prem")) else 36.0
    st.session_state.setdefault("tc_fa", round((live.get("a_fund") or 0.0) * 100, 5))
    st.session_state.setdefault("tc_fb", round((live.get("b_fund") or 0.0) * 100, 5))
    i1, i2, i3 = st.columns(3)
    with i1:
        st.markdown("**Entry**")
        s0 = st.number_input("SKHYNIX price at entry (USD)", value=float(round(s_a, 1)), step=1.0, key="tc_s0")
        p0 = st.number_input("Premium at entry (%)", value=float(round(p_now, 2)), step=0.5, key="tc_p0")
        units = st.number_input("Units (share-equivalents)", value=10.0, min_value=0.0, step=1.0, key="tc_units",
                                help="One unit = long 1 SKHYNIX, short 10 SKHY.")
    with i2:
        st.markdown("**Exit**")
        p1 = st.number_input("Premium at exit (%)", value=25.0, step=0.5, key="tc_p1")
        chg = st.number_input("SKHYNIX price change to exit (%)", value=0.0, step=1.0, key="tc_chg")
        days_hold = st.number_input("Holding period (days)", value=30.0, min_value=0.0, step=1.0, key="tc_days")
    with i3:
        st.markdown("**Costs and funding (hourly, %)**")
        fa_in = st.number_input("SKHYNIX funding per hour (%)", step=0.0005, format="%.5f", key="tc_fa")
        fb_in = st.number_input("SKHY funding per hour (%)", step=0.0005, format="%.5f", key="tc_fb")
        fee_bps = st.number_input("Fee per leg per side (bps)", value=4.5, min_value=0.0, step=0.5, key="tc_fee")
        lev = st.number_input("Leverage on posted margin", value=3.0, min_value=1.0, max_value=10.0, step=0.5, key="tc_lev")

    sc = Scenario(s0=s0, p0=p0 / 100, s1=s0 * (1 + chg / 100), p1=p1 / 100, hours=days_hold * 24,
                  f_a=fa_in / 100, f_b=fb_in / 100, fee=fee_bps / 1e4)
    r = evaluate(sc)
    be = breakeven_exit_premium(sc)
    st.markdown("##### 3 · Result")
    o = st.columns(6)
    o[0].metric("Price P&L", usd(r.price * units, 0), help="S₀·p₀ − S₁·p₁ per unit: the change in the dollar premium.")
    o[1].metric("Funding P&L", usd(r.funding * units, 0), delta=f"{carry_apr(sc.f_a, sc.f_b, sc.p0) * 100:+.0f}% APR on share notional", delta_color="off")
    o[2].metric("Fees", usd(-r.fees * units, 0))
    o[3].metric("Total", usd(r.total * units, 0))
    o[4].metric("Return on margin", pct(r.return_on_margin(lev), 1), delta=f"{r.annualised(lev, sc.hours) * 100:+.0f}% annualised" if sc.hours > 0 else None, delta_color="off")
    o[5].metric("Breakeven exit premium", pct(be, 2), help="Exit premium at which total P&L is zero with these prices, funding and fees.")
    st.caption(md(f"Notional at entry {usd(r.notional_open * units, 0)} ({usd(r.v_a_open * units, 0)} long SKHYNIX, {usd(r.v_b_open * units, 0)} short SKHY) · "
                  f"margin at {lev:.1f}x {usd(r.notional_open * units / lev, 0)} · {sc.hours:.0f} hours · funding assumed constant, price path linear, "
                  "no liquidation or basis risk modelled."))

    st.markdown("##### 4 · Sensitivity: return on margin by exit premium and holding period")
    exits = [p0, p0 - 2.5, p0 - 5, p0 - 10, p0 - 15, p0 - 20, 10.0, 5.0, 0.0]
    exits = sorted({round(x, 2) for x in exits}, reverse=True)
    horizons = [1, 7, 14, 30, 60, 90, 180]
    g = grid(sc, [x / 100 for x in exits], horizons, lev)
    gdf = pd.DataFrame(g, index=[f"{x:+.1f}%" for x in exits], columns=[f"{h}d" for h in horizons])

    def cell_color(v: float, full: float = 0.5) -> str:
        """Red for losses, green for gains, opacity by size; saturates at ±50% return. No matplotlib needed."""
        if v != v:
            return ""
        x = max(-1.0, min(1.0, v / full))
        r, g, b = (208, 59, 59) if x < 0 else (12, 163, 12)
        return f"background-color: rgba({r},{g},{b},{abs(x) * 0.55:.2f})"

    st.dataframe(gdf.style.format("{:+.1%}").map(cell_color), width="stretch")
    st.caption("Rows: exit premium. Columns: days held. Same SKHYNIX price change, funding and fees as above. "
               "Read the first row for what the carry alone does; read down a column for what compression is worth.")


# ---------------------------------------------------------------- unwind tab
with tab_calc:
    live = st.session_state.get("last_good")
    p_now = live["mark_prem"] * 100 if live and ok(live.get("mark_prem")) else 36.0
    st.markdown("**If the premium compresses with the Seoul share unchanged, how far does the ADR fall?** "
                "ADR move = (1 + target) / (1 + now) − 1. A 36% premium unwinding to parity is −26.5%, not −36%.")
    c1, c2 = st.columns([1, 1])
    with c1:
        p0 = st.number_input("Premium now (%)", value=float(round(p_now, 2)), step=0.5)
        p1 = st.slider("Target premium (%)", min_value=-10.0, max_value=80.0, value=10.0, step=0.5)
        st.metric("ADR move, Seoul flat", pct(unwind_move(p0 / 100, p1 / 100), 1))
        st.metric("Seoul move needed instead, ADR flat", pct((1 + p0 / 100) / (1 + p1 / 100) - 1, 1),
                  help="How far the Seoul share would have to rise to close the gap if the ADR did not move.")
    with c2:
        targets = [30, 25, 20, 15, 10, 5, 0]
        st.dataframe(pd.DataFrame({"target premium": [f"{t}%" for t in targets],
                                   "ADR move": [pct(unwind_move(p0 / 100, t / 100), 1) for t in targets]}),
                     hide_index=True, width="stretch")
        st.caption("TSMC's ADR premium has spent most of the last twenty years between 3% and 25%; the research note explains why the level at which this premium settles is a supply decision.")


# ---------------------------------------------------------------- TSMC tab
@st.cache_data(ttl=86400, show_spinner="Loading TSMC history…")
def load_tsmc():
    snapshot = ROOT / "data" / "tsmc_premium.csv"
    try:
        rows, dropped = tsmc.fetch_all()
        if len(rows) < 1000:
            raise RuntimeError("short series")
        source = f"live (Yahoo closes, Federal Reserve H.10 FX) · {len(dropped)} bad vendor prints dropped"
    except Exception as e:
        rows, source = tsmc.load_csv(snapshot), f"snapshot data/tsmc_premium.csv (live fetch failed: {e})"
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["date"])
    df["premium_pct"] = df["premium"] * 100
    return df, source


with tab_tsmc:
    st.markdown("**The same premium, twenty-six years earlier.** TSM (NYSE, 1 ADS = 5 shares) against 2330.TW in dollars: "
                "premium = TSM / (5 × 2330.TW ÷ USDTWD) − 1, daily closes, Taipei close against the New York close of the same date.")
    try:
        tdf, tsrc = load_tsmc()
    except Exception as e:
        tdf, tsrc = pd.DataFrame(), str(e)
    if tdf.empty:
        st.error(f"TSMC data unavailable: {tsrc}")
    else:
        r1, r2 = st.columns([2, 3])
        with r1:
            trange = st.radio("Range", ["All (2000→)", "2000–2004", "2005–2019", "2020→", "Last 12 months"], horizontal=False, key="tsmc_range")
        lo, hi = {"All (2000→)": ("1999-06-01", None), "2000–2004": ("2000-01-01", "2004-12-31"), "2005–2019": ("2005-01-01", "2019-12-31"),
                  "2020→": ("2020-01-01", None), "Last 12 months": ((pd.Timestamp.today() - pd.Timedelta(days=365)).strftime("%Y-%m-%d"), None)}[trange]
        sub = tdf[tdf["time"] >= lo]
        if hi:
            sub = sub[sub["time"] <= hi]
        with r2:
            m = st.columns(4)
            imax, imin = sub["premium_pct"].idxmax(), sub["premium_pct"].idxmin()
            m[0].metric("Latest", pct(tdf["premium"].iloc[-1]), help=f"{tdf['date'].iloc[-1]}")
            m[1].metric("Mean in range", pct(sub["premium"].mean()))
            m[2].metric("High", pct(sub.loc[imax, "premium"]), help=str(sub.loc[imax, "date"]))
            m[3].metric("Low", pct(sub.loc[imin, "premium"]), help=str(sub.loc[imin, "date"]))
            st.caption(f"{len(sub):,} daily closes · {sub['date'].iloc[0]} → {sub['date'].iloc[-1]} · source: {tsrc}")

        fig = go.Figure()
        floor = min(sub["premium_pct"].min(), 0) - 3
        fig.add_trace(go.Scatter(x=sub["time"], y=[floor] * len(sub), mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=sub["time"], y=sub["premium_pct"], mode="lines", name="TSMC ADR premium", line=dict(color=C_PREM, width=1.5),
                                 fill="tonexty", fillcolor="rgba(144,133,233,0.10)", hovertemplate="%{y:+.1f}%<extra>TSM premium</extra>"))
        if trange == "All (2000→)":
            fig.add_trace(go.Scatter(x=[pd.Timestamp(d) for d, _, _ in tsmc.REPORTED], y=[v for _, v, _ in tsmc.REPORTED], mode="markers+text",
                                     text=[f"{v:.0f}%" for _, v, _ in tsmc.REPORTED], textposition="top center", name="reported, pre-series",
                                     marker=dict(symbol="diamond-open", color=C_WARN, size=10),
                                     hovertemplate="%{text} · %{customdata}<extra>reported, not computed</extra>",
                                     customdata=[n for _, _, n in tsmc.REPORTED]))
        for d, label in tsmc.EVENTS:
            ts = pd.Timestamp(d)
            if sub["time"].min() <= ts <= sub["time"].max():
                fig.add_vline(x=ts, line_dash="dot", line_color=C_MUTED, line_width=1)
                fig.add_annotation(x=ts, y=1, yref="paper", text=label, showarrow=False, xanchor="left", yanchor="top", font=dict(size=11, color="#b7b2c5"))
        skhy_live = st.session_state.get("last_good")
        if skhy_live and ok(skhy_live.get("mark_prem")):
            fig.add_hline(y=skhy_live["mark_prem"] * 100, line_dash="dash", line_color=C_ADR, line_width=1,
                          annotation_text=f"SKHY now {skhy_live['mark_prem'] * 100:+.1f}%", annotation_position="bottom right")
        base_layout(fig, 380, ysuffix="%")
        fig.update_yaxes(range=[floor, max(sub["premium_pct"].max(), 120 if trange == "All (2000→)" else 0) + 8])
        st.plotly_chart(fig, width="stretch", key="tsmc_chart")
        st.caption("Diamonds are figures reported in the press for 1999–2000, before the Taiwan share history begins; they are not computed from data. "
                   "Dotted lines mark events. The dashed line is SKHY's live mark premium for comparison.")

        st.markdown("**Regimes: premium by year**")
        ydf = pd.DataFrame(tsmc.yearly(tdf.to_dict("records")))
        bar = go.Figure(go.Bar(x=ydf["year"], y=ydf["mean"] * 100, marker_color=C_PREM, hovertemplate="%{y:+.1f}% mean<extra>%{x}</extra>"))
        bar.add_trace(go.Scatter(x=ydf["year"], y=ydf["max"] * 100, mode="markers", name="year high", marker=dict(color=C_WARN, size=6),
                                 hovertemplate="%{y:+.1f}% high<extra>%{x}</extra>"))
        base_layout(bar, 260, ysuffix="%")
        bar.update_layout(showlegend=False, xaxis=dict(type="category"))
        st.plotly_chart(bar, width="stretch", key="tsmc_yearly")
        c1, c2 = st.columns([3, 2])
        with c1:
            show = ydf.copy()
            for c in ("mean", "median", "min", "max"):
                show[c] = show[c].map(lambda v: f"{v * 100:+.1f}%")
            st.dataframe(show.rename(columns={"year": "Year", "mean": "Mean", "median": "Median", "min": "Low", "max": "High", "days": "Days"}),
                         hide_index=True, width="stretch", height=320)
        with c2:
            st.markdown(
                "**Reading it.** The bubble regime (2000: high double digits) compressed through the 2000–01 bust and repeated "
                "ADS supply from conversion sales; Taiwan scrapped QFII in October 2003. From about 2010 the premium settled into low single "
                "digits, rose with foreign demand from 2020, and spiked again in the 2024 AI rally. It has never gone to zero for long: "
                "Taiwan shares still cannot be deposited freely, and index funds must buy the ADR.\n\n"
                "**Caveats.** Taiwan share history starts January 2000, not at the October 1997 listing. Same-date closes carry a 15-hour gap "
                "between Taipei and New York. Both series are split-adjusted by the same stock-dividend events, so the 5:1 ratio holds; "
                "small transient errors are possible on ex-dates. FX is the Fed's noon buying rate, forward-filled."
            )
        st.download_button("Download TSMC premium CSV", tdf[["date", "tsm", "tw", "fx", "premium_pct"]].to_csv(index=False).encode(),
                           file_name="tsmc_premium.csv", mime="text/csv", key="dl_tsmc")


# ---------------------------------------------------------------- about tab
with tab_about:
    st.markdown(
        """
**What this is.** A monitor for the premium between SK hynix's Nasdaq ADSs and its Seoul common shares,
read through the two Hyperliquid HIP-3 perpetuals that track them 24/7. It is the Streamlit edition of the
same tool that ships as a single HTML file in this repo; both share the tested Python layer in `analysis/`.

**Three premiums.** *Mark* uses Hyperliquid mark prices (what trades around the clock). *Oracle* uses the
deployer oracles, which only move while the underlying venue trades, so outside KRX or Nasdaq hours one leg
is stale. *Executable* uses the top of each order book in each direction.

**Carry.** For long SKHYNIX / short SKHY, hourly carry = SKHY funding − SKHYNIX funding. Positive means the
position receives. Hyperliquid pays funding hourly; a positive rate means longs pay shorts.

**Why the premium exists.** The ADS quota is 2.5% of the company and was exhausted at listing; new ADSs can
only be created against cancelled ones, and nobody cancels a security trading at a premium. Raising the
quota needs a board resolution and Korean and US registrations. See `research/skhy-adr-premium.html`.

**Data.** Hyperliquid public info API, REST polling. History from candle closes, which track the oracles
within roughly 0.5%. Sessions ignore holidays. Nothing here is investment advice.
        """
    )
