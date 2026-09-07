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

## 14. Scenario calculator as a pure function with a closed-form breakeven

**Context.** "What do I earn if the premium goes from here to there over N days at this
funding rate?" is the question every user of the backtest asked next. **Decision.** A
`Scenario` dataclass and `evaluate()` in `analysis/calc.py`, with price P&L written as the
change in the dollar premium (S₀·p₀ − S₁·p₁), funding on each leg's average notional, fees on
open and close, and a closed-form breakeven exit premium (total P&L is linear in p₁). The app
adds a window selector that fills the funding inputs with the mean hourly rate over 24h, 7d,
30d, since listing or a custom range. **Why.** The math is testable in isolation; the
breakeven is exact rather than searched; and averaging funding over a chosen window is
labelled in the UI as an assumption, not a forecast, because the backtest already showed how
far a snapshot can be from the realised path. **Cost.** Constant funding and a linear price
path; no liquidation or basis modelling.

## 15. TSMC history from free sources, with the gaps shown rather than filled

**Context.** The research note leans on TSMC 1999–2005 as the closest analogue, and the
user wanted it on the dashboard from the 1997 listing. **Sources tried.** Yahoo has TSM from
1997 and 2330.TW from 2000 but USD/TWD only from 2004; Stooq sits behind a bot challenge;
FRED timed out from this network; the Taiwan exchange's own endpoint starts in 2010; the
BIS API rejected the dataflow. The Federal Reserve's H.10 historical pages carry daily
USD/TWD from 1990 and parse cleanly. **Decision.** Yahoo split-adjusted closes on both sides
(both carry the same stock-dividend events, so the 5:1 ratio holds), Fed FX as the
authoritative rate with Yahoo used only after the last weekly H.10 print, a snapshot CSV
committed as a fallback, and the pre-2000 period represented by labelled press figures
rather than interpolation. **Why.** Yahoo's FX history had two impossible ticks (1.80 and
3.67 to the dollar) that produced −90% premiums; preferring the Fed series removed them at
the source, and a range check drops anything similar with a visible count. This is
different from decision 6: those were vendor errors, not market prints. **Cost.** The
computed series starts 27 months after the listing; same-date closes are 15 hours apart.

## 16. One pipeline for every precedent, validated against the literature before trusting it

**Context.** Infosys was the note's strongest analogue for persistence and the user wanted
it on the dashboard. **Decision.** Generalise the TSMC script into `dr_history.py` with a
`Case` record per company (symbols, Fed FX file, ADS ratio, sanity bounds, reported figures,
events) and one set of functions; `tsmc.py` stays as a thin wrapper so nothing that
imported it breaks. **Validation.** The computed Infosys annual means for 2001–2005 (56.9,
61.1, 46.0, 48.6, 35.2%) match Saxena's published table (57, 61, 46, 49, 36%) and March 2000
lands on Lamont's 136%. That check also caught a mistake of mine: I had added a factor for the
early-2000 window where Mumbai and New York went ex a split on different dates, and the data
showed the adjusted series was already continuous there, so the factor produced +300%
prints and was removed. The mechanism stays (tested) with no case using it. **Why.** A
series that reproduces published numbers can carry an argument; one that does not is a
liability however pretty the chart. **Cost.** Yahoo is the only free source for the home
shares, so the pipeline inherits its corporate-action handling.

## 17. Add a control group, and reconcile corporate actions instead of trusting the vendor

**Context.** The user asked for the fifteen companies in a paper's dataset: five Indian, five
Mexican, five Brazilian. Four have delisted ADRs with no surviving free history. The other
ten built, but the first pass produced impossible series: Itaú's ADR at an 18% discount for
six years, Bradesco's at a 47% premium for nine, América Móvil at a constant +5% for two
decades. **Diagnosis.** A freely convertible ADR cannot hold a step-shaped premium, so every
step had to be a data artefact. Pulling both listings' split-event lists showed each step
matching a bonus issue Yahoo had recorded on one listing only, in the direction and size the
arithmetic predicts (a home-only factor f inflates the computed premium by f for every
earlier date; an ADR-only factor deflates it). **Decision.** Encode per-case correction
factors derived from the event lists and confirmed against the observed steps; start a
series later where a mismatch could not be traced to an event; list the four delisted
names explicitly as unavailable rather than dropping them silently. **Validation.** Wipro's
corrected 2001–2005 means match the published table within a point; every convertible ADR
sits within a percent of parity in every year. **Why it matters.** The control group turns
the argument from "restricted ADRs have premiums" into "restriction is the only thing that
produces one": same vendor, same method, same years, eight names at zero and four with
premiums. **Cost.** Shorter coverage for four names, and a dependence on Yahoo's event lists
being merely incomplete rather than wrong.
