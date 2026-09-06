# SKHYNIX / SKHY premium monitor

A small, self-contained toolkit for one question: **why do SK hynix's Nasdaq ADSs trade
about a third above the same shares in Seoul, and how long can that last?**

Four parts, one tested data layer:

| Part | What it is | Where |
|---|---|---|
| Streamlit app | Live monitor with mark, oracle and executable premiums, funding carry, session clocks, history charts with range statistics, alerts, an interactive carry backtest and an unwind calculator. | [`app.py`](app.py) |
| Analysis layer | Standard-library Python: API client, derived metrics, premium series and statistics, venue sessions, carry backtest. 22 unit tests. | [`analysis/`](analysis), [`tests/`](tests) |
| Research note | Why restricted-conversion depositary receipts carry premiums, what ended TSMC's and Infosys's, and what would end this one. Sources graded by quality. | [`research/skhy-adr-premium.html`](research/skhy-adr-premium.html) |
| Zero-install monitor | The original single HTML file: WebSocket feed, same tiles and charts, no Python needed. For a machine where nothing can be installed. | [`index.html`](index.html) |

## The markets

| UI ticker | API coin | Underlying |
|---|---|---|
| SKHYNIX | `xyz:SKHX` | One SK hynix common share (KRX 000660), in USD via the deployer's KRW oracle |
| SKHY | `xyz:SKHY` | One SK hynix ADS (Nasdaq: SKHY), in USD |

Both are HIP-3 perpetuals on Hyperliquid's XYZ dex. Each ADS represents one-tenth of a
share, so everything compares **SKHY × 10** with **SKHYNIX**:

```
premium      = (SKHY × 10) / SKHYNIX − 1
unwind move  = (1 + p_target) / (1 + p_now) − 1        # 36% → 0% is −26.5%, not −36%
carry (1h)   = funding(SKHY) − funding(SKHYNIX)          # long SKHYNIX / short SKHY
```

## Quick start

```bash
python -m pip install -r requirements.txt   # streamlit, plotly, pandas
python -m streamlit run app.py              # opens http://localhost:8501
```

The `python -m` form works even when Python's `Scripts` folder is not on your PATH
(the plain `streamlit` command needs it).

```bash
python -m unittest discover -s tests -v                    # 22 offline tests, no network
HL_LIVE=1 python -m unittest tests.test_premium.LiveSmoke   # checks both markets exist and the ratio is sane
python analysis/premium.py --interval 1d --csv data/premium_daily.csv
python analysis/carry_backtest.py --start 2026-07-15 --csv data/carry_backtest.csv
```

The analysis scripts and tests need nothing beyond Python 3.10+. The HTML monitor needs
nothing at all: open [`index.html`](index.html) in a browser.

## How it fits together

```mermaid
flowchart LR
  HL[(Hyperliquid info API)]
  HL -- "metaAndAssetCtxs, l2Book\nevery few seconds" --> M[analysis/metrics.py\nderive()]
  HL -- "candleSnapshot\nfundingHistory" --> P[analysis/premium.py\nanalysis/carry_backtest.py]
  M --> A[app.py\nStreamlit fragments]
  P --> A
  P --> CSV[(data/*.csv)]
  CSV --> R[research note]
  S[analysis/market_hours.py] --> A
  T[tests/] -. pure functions .-> M & P & S
  HL -- "WebSocket" --> H[index.html]
```

Everything a number on screen depends on lives in `analysis/` as a pure function with a
test. `app.py` only fetches, formats and lays out.

## What the app shows

- **Monitor**: hero premium with change vs 24h and vs the 30-day mean, unwind-to-parity move, 24h sparkline; tiles for oracle premium (with "oracle last moved" ages, since a stale leg is the norm outside KRX or Nasdaq hours), executable premium from the top of both books, funding carry in %/h and APR, implied Seoul price in won, KRX and Nasdaq countdowns; market details table; alert log.
- **History** (24H / 7D / 30D / All): premium with min, max, mean, standard deviation, percentile and z-score; both legs on one axis; annualised funding for both; CSV download and a data table.
- **Carry backtest**: long 1 SKHYNIX / short 10 SKHY from any date since listing, hourly, with the exchange's actual funding prints. Price, funding and total P&L, drawdown, CSV download.
- **Unwind calculator**: how far the ADR falls for any target premium, and how far Seoul would have to rise instead.
- **Alerts**: upper/lower thresholds and a |z| ≥ 2 regime alert, edge-triggered with hysteresis, shown as toasts and kept in a log.

Live data is polled over REST inside auto-refreshing Streamlit fragments (2 to 15 s); history is cached for a minute, baselines and backtests for five.

## Findings so far (6 Sep 2026)

| | |
|---|---|
| Premium at listing (9 Jul) | about +7% close, priced 5.8% *below* Seoul |
| Premium now | +37% |
| Range since 15 Jul | +24% to +42%, mean +34%, sd 4 pp |
| Correlation of daily premium change with Seoul move | −0.10 (the premium is set on the US side) |
| ADS float | 177.9M ADSs = 2.44% of the company; conversion quota exhausted at listing |
| Compression trade, 15 Jul → 6 Sep (long 1 SKHYNIX / short 10 SKHY) | price P&L ≈ 0, funding −6% APR, max drawdown 22% of notional |

The last row is the reason the tool exists. On any given day the carry tile can show a
three-digit APR for the compression trade; over seven weeks the funding netted out
negative and the position spent most of its life under water. The premium is a
scarce-security price, not a mispricing with a timer on it. The research note works
through the history.

## Design decisions

Short version; the reasoning and the rejected alternatives are in [`docs/decisions.md`](docs/decisions.md).

- Streamlit for the desk version because the desk is Python: the app imports the same tested functions the scripts use, and adding a backtest tab was an afternoon, not a rewrite. The HTML version is kept for machines where nothing can be installed.
- Three premiums, not one: mark (what trades 24/7), oracle (what the underlyings last printed), executable (what the top of book would fill). They answer different questions and diverge outside exchange hours.
- Data anomalies are flagged, not filtered: the 13 Jul Seoul oracle print is left in the series and annotated.
- Pure functions for anything that becomes a number; I/O at the edges; tests offline by default.

## Limitations

- Session indicators ignore exchange holidays.
- History comes from perp candle closes, which track the oracles within roughly 0.5% but are not exchange prints.
- The Streamlit app polls REST every few seconds per open session; a shared collector would be needed for many users.
- No persistence: the alert log lives in the session. Export CSV or run the scripts for durable data.
- Borrow fees and depositary-level ADS counts are not available from public APIs and are tracked by hand in the research note.

## Roadmap

- Persist the tick stream (SQLite) and alert log; Telegram or email delivery for alerts.
- Model the premium against its drivers: US flow proxies, funding, short interest, Korean retail net buying.
- Extend the same layer to other cross-listed pairs on Hyperliquid (Samsung, Kioxia if listed).

## How this was built

Built over three days with Claude Code as a pair, directed and reviewed by hand. The
workflow that mattered: pin the market mapping from the API and the exchange UI before
writing a line, verify every number that enters the research note against a primary source
or mark it as unverified, test the arithmetic that people get wrong (the unwind, the funding
sign), and look at the rendered result rather than trust the code.

Nothing here is investment advice.
