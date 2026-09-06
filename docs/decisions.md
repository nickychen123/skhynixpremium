# Decision log

Short records of the choices that shaped the project, in the order they were made.
Each one names the alternative that was rejected and what it would cost to reverse.

## 1. Pin the market mapping before building

**Context.** The request named "SKHYNIX" and "SKHY". The API has no `SKHYNIX`; it has
`xyz:SKHX` and `xyz:SKHY`, plus a spot token `SKHYX` (a tokenised xStock) and, on other
dexes, nothing. **Decision.** Confirm from three directions before coding: the API metadata,
the Hyperliquid UI (tab title "SKHYNIX (xyz)" for `xyz:SKHX`), and the SEC filing for the
10:1 ADS ratio. **Why.** A wrong ratio or wrong coin produces a plausible-looking number
that is simply wrong; a premium of 35% and a premium of 3.5% both look like data.
**Reversal cost.** None; the mapping is three constants.

## 2. One HTML file, no build step

**Alternatives.** A React/Vite app; a Python backend with a web front end.
**Decision.** A single file that opens from disk and talks to the exchange directly.
**Why.** The user of a tool like this is often on a locked-down desk machine. A file that
needs no runtime, no package install and no server is the one that actually gets used.
Hyperliquid's API allows any origin, so nothing is lost.
**Cost.** No module system, so JavaScript cannot be unit-tested without extraction. Mitigated
by keeping the tested reference implementation of the math in Python (`analysis/`). If the
JavaScript grows, extract the pure functions into a module and test them with Node.

## 3. Direct exchange connection: WebSocket first, REST fallback

**Decision.** Subscribe to `activeAssetCtx` and `l2Book` for both coins over WebSocket; if
the socket drops or goes quiet for 20 s, poll `metaAndAssetCtxs` and `l2Book` every 5 s
until it reconnects (exponential backoff, capped at 30 s). **Why.** The socket gives
sub-second updates for free; the fallback keeps the page honest during outages, and the
connection state is always visible in the header so nobody reads a stale number as live.
**Cost.** Each open tab is its own API client; a desk with twenty tabs open would hit rate
limits. A shared collector would fix that (see roadmap).

## 4. Three premiums rather than one

**Decision.** Show mark, oracle and executable premiums side by side.
**Why.** They answer different questions. Oracle premium is the real-world gap between the
two exchanges but at least one leg is always stale (KRX and Nasdaq never overlap). Mark
premium is what Hyperliquid's 24/7 books believe the gap will be. Executable premium is what
you could actually do at the top of book right now, in each direction. A single "premium"
number hides which of these you are looking at.

## 5. History from candle closes, live point appended

**Decision.** Charts use `candleSnapshot` closes (5m to 4h depending on range) with the
live mark premium appended as the last point; refresh every 60 s. **Why.** Simple,
consistent across ranges, and cheap. **Cost.** Candles are perp trades, not exchange prints;
they track the oracles within about 0.5%. Documented in the note and the README.

## 6. Flag anomalies, do not filter them

**Context.** On 13 Jul a bad pre-market print in Seoul moved the SKHX oracle roughly 20%
and the premium spiked. **Decision.** Leave it in the series and annotate it in the research
note. **Why.** A tool that silently edits data will eventually edit something real.
Filtering is a modelling decision and belongs in the analysis layer where it is visible.

## 7. Sessions and staleness, not hour filters

**Decision.** Show KRX and Nasdaq session state with countdowns and, on the oracle tile,
how long each oracle has been unchanged. **Why.** Readers need to know *which* leg is stale
right now; hiding the premium outside hours would hide the most interesting periods.
**Cost.** Holidays are not handled; a calendar would be the fix.

## 8. Alerts are edge-triggered with hysteresis

**Decision.** Thresholds fire once on crossing and re-arm 0.1 pp back inside the band; the
z-score alert fires at |z| ≥ 2 and re-arms inside 1.5. **Why.** A level-triggered alert on a
series with 3 pp daily swings would fire continuously. **Cost.** A slow drift across a
threshold produces one alert, not a reminder; that is the intended trade.

## 9. Chart palette validated, table twins everywhere

**Decision.** Series colours come from a palette that passes colour-vision-deficiency
separation and contrast checks in both light and dark themes; every chart has a table view.
**Why.** Small cost, and it is the kind of thing that separates a tool from a demo.

## 10. Python analysis with no dependencies; tests offline by default

**Decision.** `urllib` and `statistics` only; unit tests run without network; the live
smoke test is opt-in with `HL_LIVE=1`. **Why.** Anyone can run it anywhere, and CI stays
deterministic. **Cost.** No pandas ergonomics; acceptable at this size.

## 11. Research note as an HTML page with embedded data, sources graded

**Decision.** Write the note with the same tooling as the dashboard, embed the series, and
label every figure as primary-verified, press-verified, own series, or unverified working
estimate. **Why.** The brief mixed reconstructed numbers with primary ones; the grading is
the most useful thing the note adds, because it tells the reader what to check before the
numbers go into a model.

## 12. Dashboard not published as a hosted page

**Context.** Hosted artifact pages run under a content-security policy that blocks
fetch and WebSocket to external hosts. **Decision.** Ship the dashboard as a local file and
publish only the (static) research note. **Why.** A live dashboard that cannot reach its
data is worse than no dashboard.

## 13. Rebuild the dashboard in Streamlit; keep the HTML file as the zero-install edition

**Context.** Decision 2 chose a single HTML file for portability. Two days in, the analysis
layer had grown into tested Python (premium math, funding sign, sessions, backtest) that the
JavaScript could only mirror by hand, and the users this is for work in Python.
**Decision.** `app.py` in Streamlit, importing the same `analysis/` functions the scripts and
tests use. The live panel is an auto-refreshing fragment polling REST every few seconds;
history, baselines and backtests are cached. The HTML file stays as the option for a
machine where nothing can be installed. **Why.** One implementation of every number, in
the language the desk reads and extends; a backtest tab and a calculator cost an afternoon.
**Cost.** A Python environment and a server process; REST polling instead of the
WebSocket feed (2 to 15 s latency rather than sub-second); each browser session is its own
API client. **Reversal cost.** None; the HTML edition still works and is kept in the repo.
The lesson worth stating in an interview: the first version was right for the first
question (does this premium exist and what is it now) and wrong for the second (what does
holding the trade actually cost), and the rewrite followed the question, not the fashion.
