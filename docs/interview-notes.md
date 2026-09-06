# Interview notes: talking about this project

Role: AI specialist at a trading firm, building tools and applying AI to the workflow.
What they are really testing: can you turn a vague trading question into a working tool,
check your own numbers, explain trade-offs, and use AI without outsourcing judgement.

## The two-minute version

"SK hynix listed ADSs on Nasdaq in July and they immediately traded 30 to 50 percent above
the same shares in Seoul. I built a monitor for that premium on Hyperliquid, where both legs
trade as perps 24/7, then went back to the primary sources to answer the question that
actually matters: how long can a premium like that last when arbitrage is blocked?
The answer is that it is a supply decision by the issuer, not a market process. TSMC and
Infosys carried 30 to 60 percent premiums for years and both compressed only after
sponsored ADS supply arrived. I backtested the obvious trade and found the carry people
quote is real on any given day but netted out negative over seven weeks, with a 22 percent
drawdown for zero price P&L."

## Stories in STAR form

### 1. Scoping an ambiguous request (attention to detail)
- **S**: The request named "SKHYNIX" and "SKHY". The API has no SKHYNIX.
- **T**: Find the right instruments before writing code.
- **A**: Queried every HIP-3 dex, found `xyz:SKHX` and `xyz:SKHY` plus a tokenised spot
  stock with a similar name, opened the exchange UI to confirm the display name, and pulled
  the ADS ratio from the SEC filing rather than assuming 1:1.
- **R**: A 35% premium instead of a meaningless 3.5% or 3,500% one. Lesson: a plausible number
  is the most dangerous kind.

### 2. Building the tool a trader would actually use (product sense)
- **S**: "A dashboard for the premium" could mean one number on a page.
- **A**: Split it into three premiums (mark, oracle, executable) because they diverge outside
  exchange hours and answer different questions; added funding carry, session countdowns,
  oracle staleness, executable top-of-book, alerts with hysteresis, CSV export.
- **R**: Every tile answers a question someone on a desk would ask next.

### 3. Verifying numbers before trusting them (rigour)
- **S**: The research brief mixed primary figures with reconstructed ones; press reports
  contradicted each other (a "25% conversion cap" that turned out to be a re-issuance reserve;
  a data site showing 0% institutional ownership).
- **A**: Read the F-1 amendment for the share count, lockup and the reason for the 2.5% cap
  (SK square's 20% holding-company floor); graded every number in the note as primary,
  press, own series, or unverified; flagged what I could not confirm (borrow fees).
- **R**: The note's most useful feature is the grading. It tells the reader what to check
  before the numbers enter a model.

### 4. Testing the arithmetic people get wrong (engineering discipline)
- **S**: "A 36% premium means 36% downside" is wrong; the funding sign convention is easy to flip.
- **A**: Put the reference math in Python with unit tests: unwind is 1/(1+p) − 1, so 36% → −26.5%;
  a negative funding rate means the long leg receives. Live smoke test is opt-in so CI is deterministic.
- **R**: Eleven tests, all offline, all fast. The dashboard's JavaScript mirrors the tested code.

### 5. Letting the backtest disagree with the tile (intellectual honesty)
- **S**: The carry tile showed +250% APR for long-Seoul / short-ADR on the day I looked.
- **A**: Backtested the position hourly from 15 Jul with actual funding prints.
- **R**: Price P&L about zero, funding −6% APR over the period, max drawdown 22% of notional.
  The tile was not wrong; it was a snapshot. The tool now exists to keep people from
  mistaking a snapshot for an expectancy.

### 6. Using AI as a pair, not an oracle (the role itself)
- How I used it: decomposition into parallel research threads (filings, press, academic
  papers, API probing at the same time); generating the first draft of code and prose;
  running validation scripts (palette checks, tests, live smoke tests) before believing output.
- Where I overrode it or caught it: press summaries that mislabelled years; a data site's
  garbage fields; the temptation to filter the 13 Jul oracle anomaly instead of flagging it;
  a hosted-page option that could not reach live data because of its security policy.
- Rule I follow: anything that becomes a number in front of a trader gets a source or a test.

### 7. Trade-offs I chose and can defend
- Streamlit for the desk edition, HTML for the zero-install edition: one tested implementation of every number, in the language the desk uses. Cost: a Python environment and REST polling instead of the WebSocket feed.
- Direct exchange connection per session: simplicity over scale. Cost: rate limits with many users; fix is a shared collector.
- Flag anomalies rather than filter: transparency over cleanliness.
- Not publishing the dashboard as a hosted page: a live tool that cannot reach its data is worse than none.

### 8. Rewriting when the question changed (judgement, not sunk cost)
- **S**: Version one was a single HTML file, chosen for portability. It answered "does this premium exist and what is it now."
- **T**: The next question was "what does holding the trade actually cost," which needed a backtest, a calculator and the tested Python math on screen.
- **A**: Rebuilt the dashboard in Streamlit on top of the existing `analysis/` layer, so the app imports the same functions the tests cover. Kept the HTML file as the zero-install option rather than deleting it.
- **R**: A backtest tab and a calculator in an afternoon, every number on screen with a unit test behind it, and a decision log entry that says why the first choice was right for its question and wrong for the next one.

## Likely behavioural questions and which story to use

| Question | Story |
|---|---|
| Tell me about a project you are proud of | Two-minute version, then 2 and 5 |
| A time you found an error in data or in someone's work | 3 (the "25% cap") or 1 |
| A time you had to make a decision with incomplete information | 3 (borrow fees unknown; graded and moved on) |
| How do you use AI tools in your work | 6, with the rule at the end |
| A time your first answer was wrong | 5 (carry snapshot vs backtest) |
| How do you decide what to build first | 2 (three premiums; the question a trader asks next) |
| Describe a technical trade-off | 7 |
| A time you changed your approach mid-project | 8 |
| What would you do differently | Roadmap: persist ticks, shared collector, driver model, holiday calendar |

## Domain points worth having ready

- Premium = ADS × 10 / share − 1; unwind = 1/(1+p) − 1.
- Why it persists: one-way fungibility, quota exhausted at listing, headroom only from cancellations, raising the cap needs board + FSC + SEC (an offering in all but name), 90-day lockup to ~7 Oct.
- Why arbitrage does not close it: no convergence date, both legs ~120% annualised vol, borrow, FX, and demand still arriving (Nasdaq-100 window in December, ETFs, retail on both sides).
- History: TSMC 30–115% in 1999–2000, compressed via conversion sales and the 2000 bust, now ~10%; Infosys 36–61% for six years, compressed after $2.7bn of sponsored ADS supply in 2005–06; Samsung's fungible GDR sat at parity; SK hynix's own Frankfurt GDR is at parity today.
- Hyperliquid specifics: HIP-3 dexes, deployer oracles, hourly funding, mark vs oracle basis, why the Seoul-leg perp trades under its oracle when KRX is closed.

## Questions to ask them

- What does the path from "a trader has a question" to "a tool exists" look like today, and where does it stall?
- How do they validate model or LLM output before it touches a decision?
- What data do their tools consume, and who owns the plumbing?
- What did the last successful internal tool look like, and why did it get adopted?

## Demo script (if there is a screen)

1. `python -m streamlit run app.py`. Point at the hero, then the three premiums and why they differ right now (which exchange is open; the "oracle last moved" ages).
2. Switch the range to 24H, hover the chart, show the stats strip and the z-score. Set an alert in the sidebar.
3. Show the carry tile, then open the Carry backtest tab and read the drawdown against the "APR" the tile shows. That contrast is the whole point.
4. Unwind calculator: drag the target premium; note that 36% → 0% is −26.5%.
5. Open the research note, scroll to the case table and the fourteen questions with their status labels.
6. `python -m unittest discover -s tests -v`. Twenty-two tests, offline, under a second.
