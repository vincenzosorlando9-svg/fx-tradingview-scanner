# FX TradingView Scanner

Automated technical FX rotation research. **Technical candidates are not executable trade orders.**

## Mandatory full-spectrum FX scan standard (updated 2026-10-12)

**Apply to every scan, including a single pair.** Identify *why the currencies are moving now*, not just the chart direction. Audit both currencies in each cross and compare them with the rest of their currency clusters.

1. **Breaking news first:** Reuters and FXStreet; timestamp each relevant catalyst and distinguish verified event, supporting evidence and hypothesis. Identify pre-release forecasts versus post-release reaction.
2. **Economics:** releases, actual vs consensus, revisions, calendar, surprise magnitude and price response. Include China data for AUD/NZD and relevant country-specific releases.
3. **Central banks:** Fed, ECB, BoE, BoJ, RBA, RBNZ, BoC; decisions, speeches, minutes, rate path, OIS probabilities and repricing.
4. **Rates:** Trading Economics primary sovereign yields (2Y/5Y/10Y/30Y); spreads and *changes* for each currency pair, especially 2Y and OIS. Investing.com / FT for spread backup where available. Distinguish closed-market or stale yield observations.
5. **Commodities:** ForexCracked for non-crude quotes; OilPrice.com **only** for WTI/Brent. Check iron ore, copper, coal/LNG, gold, crude and other exposures relevant to each currency; timestamp changes, note conflicting signals.
6. **Cross-asset/risk:** DXY, CNH, US Treasury curve, sovereign spreads, Nikkei, VIX, equities, inflation expectations, geopolitical risk, carry unwinds and intervention risk.
7. **Currency strength:** strongest vs weakest, breadth across crosses, JPY/USD cluster acceleration and failure-to-react evidence.
8. **Positioning:** CFTC TFF, CME open interest/volume when independently verified, OANDA/IG/Myfxbook/A1Trading retail positioning, FearGreedMeter only (CNN blocked and excluded).
9. **Technical timing LAST:** fresh 15m + 30m alignment for EARLY; 1H price vs EMA20 for confirmation, EMA50 for added strength; 4H EMA10 closed-candle cross, EMA20 trend context, resistance rejection, failed breakouts and measured consolidation duration; Daily background. Check HH/HL/LH/LL, EMAs, RSI/MACD, ATR/ADR used and remaining range, nearby levels and chase risk. Do not use 5m as a detector input.
10. **Execution board:** Top 3 pair / BUY-SELL / EARLY-CONFIRMING-EXTENDED / verified price and timestamp / conditional entry / invalidation or stop / TP1 and TP2 when grounded. Target 20–30 intraday pips; don't chase mature moves. Identify news-driven risks and macro/technical disagreement.

### Accuracy and integrity rules

- A directional chart candidate is **not** a macro-confirmed trade. Classify catalysts as VERIFIED, SUPPORTING, HYPOTHESIS or UNAVAILABLE, with source and observation timestamp.
- When commodity moves oppose the technical direction, flag **COMMODITY_DIVERGENCE**; when rate differentials oppose it, flag **YIELD_DIVERGENCE**. Neither is an automatic veto.
- No invented live prices, yields, probabilities, spreads, sentiment, stops or targets. Mark missing or stale sources **UNAVAILABLE**.
- GitHub technical/volatility JSON feeds must be fresh and timestamp-checked; upstream freshness is not implied by a new local file.
- **The technical scanner and a separate no-key macro collector are automated.** Data source coverage is NOT universal; public publishers may block reads or expose only daily/delayed snapshots. No candidate is a broker-confirmed trade. Never label indicative data as live executable or publisher-date references as intraday quotes.
- Backtest signal detection without future leakage and compare calculated 4H closed-candle EMA/crossover values to TradingView before claiming trading accuracy.

### No-API-key macro collection contract (2026-10-12)

- **No paid or secret API keys required.** Do not require `TE_API_KEY` or fail the macro collection job because that variable is absent.
- Trading Economics **public bond pages** are the primary *human-readable research source*, not a guaranteed programmatic API. If access is blocked or content is stale, attempt publicly accessible Investing.com, FT, or official treasury/central-bank releases; retain source URL, market date, collection time, maturity and value.
- OIS / policy-implied rate expectations are a separate field from sovereign yields. Never substitute 2Y/5Y/10Y/30Y yields for OIS; label OIS `UNAVAILABLE` if no verifiable public observation exists.
- Collect available data independently per country and maturity. A missing field must not abort the remaining 11-pair technical scan. Use `VERIFIED`, `PARTIAL` and `MISSING` honestly; no invented or stale-as-current values.
- Verify actual GitHub publication time separately from upstream observation time. Preserve the existing technical feeds and scheduled runs.
- **Implementation:** The scheduled `.github/workflows/fx-unified-macro.yml` runs the macro collector, published-actuals and CFTC research, ADR20/session reference engine, timestamped historical change detection, unified 11-pair fusion and integrated source audit. It runs approximately every 15 minutes (GitHub scheduling may be delayed).


## Unified Macro Intelligence Engine (installed October 13, 2026)

GitHub Action: [FX Unified Macro Intelligence (No Keys, No Alerts)](.github/workflows/fx-unified-macro.yml). Runs on schedule ~:11/:26/:41/:56 UTC, with a Friday historical positioning refresh. GitHub Actions cron is best-effort.

**Two safe writer responsibilities:** Macro workflow records raw data, observed changes, headlines, ADR20 and integrated source audit every ~15m. The existing [FX Early Rotation Detector](.github/workflows/rotation.yml) exclusively publishes `fx_unified_signals.json` after each ~5m technical scan, reading the most recent usable macro snapshot (or clearly marking unavailable). It does not re-sample or update historical macro values; this prevents fake macro changes and parallel Git history conflicts.

Published files:
- `fx_macro_raw.json`: public financial source observations with publisher market dates, approximate clocks and access statuses.
- `fx_macro_snapshot.json`: normalized level/unit/source/status, same-tenor sovereign spread references and fetch-observed 15/30/60-minute changes.
- `fx_macro_history.json`: capped timestamped source samples; never rename a site download time as a publisher quote time.
- `fx_macro_news.json`: dated FXStreet headlines (Reuters only when publicly accessible) and publisher-reported economic actuals.
- `fx_economic_actuals.json`: uniquely matched actual/forecast/previous from Forex Factory public HTML; release clock is not independently proven.
- `fx_cftc_tff.json`: official dated futures-only CFTC TFF positions and futures open interest; weekly, not intraday.
- `fx_range_context.json`: completed D1 ADR20, NY17 daily running high-low context, observed M15 session ranges; NEVER contributes directional votes.
- `fx_unified_signals.json`: top five + all 11 CLOSED M15/M30 research signals; preserves technical rank (50% early opportunity, 50% trend strength), independent macro alignment, evidence and contrary catalysts. Macro missing/MIXED cannot veto the EARLY watch.
- `fx_integrated_audit.json`: per-layer actual source availability, age, verification limitations, and per-pair integrated research context.

Collectors: `fx_macro_collector.py`, `fx_ff_actuals_collector.py`, `fx_cftc_tff_collector.py`, `fx_range_context.py`. Fusion: `fx_macro_engine.py`, `build_integrated_fx_audit.py`. Regression test: `python -m unittest -v test_fx_macro_engine`.

Approved source contract: Trading Economics no-key *public* bond, policy rate and global index pages; ForexCracked indicative 11-pair reference quotes and non-crude commodities; OilPrice.com ONLY for WTI/Brent (delay disclosed); FearGreedMeter.com ONLY (CNN explicitly excluded); Forex Factory calendar and reported actuals; FXStreet and Reuters published news only when retrievable; official CFTC weekly reports. Source timestamps and explicit freshness status are mandatory. External source fields unavailable in static HTML remain unavailable rather than guessed.

**Removed by user:** options expiries, flows, volatility skew, and the entire former options layer. Do not include in the source audit or require options confirmation for a signal.

**Execution safety:** 11 pairs only. Signals rely ONLY on closed M15 and M30. H1/H4/Daily are context. The code does not create issues, send mobile/email signals, or place orders. No paid/secret API keys. Broker-verified executable bid/ask, live CME contract volume, true OIS expectations and independent intraday exchange quotes must remain `UNAVAILABLE` if no verified public observation exists. A Yahoo/ForexCracked/public quote must NEVER be called an executable broker price. Signals are provisional research, not trading instructions.


## Unified FX intelligence architecture (October 13, 2026)

**Scope:** exactly 11 approved FX pairs. The closed 15m/30m candles are the ONLY directional signal/ranking timeframes; 1H/4H/Daily are context and 5m never produces, confirms or vetoes signals. Fifty-percent early opportunity + fifty-percent trend strength ranking. Provisional early BUY/SELL watches remain permitted with mixed or unknown macro evidence. No automatic orders, API keys, new alert issues, or push notifications.

- Technical (~5 minute) workflow: `rotation.yml` publishes canonical watches and `fx_unified_signals.json` via `fx_signal_fusion_refresh.py`. It reads the freshest validated macro data and never re-samples news/yields itself.
- Macro (~15 minute) workflow: `fx-unified-macro.yml` collects approved public macro/news sources, records provenance, source timestamps, historical changes, and audits coverage. It does not overwrite the faster published signal board.
- Calendar workflow refreshes Forex Factory weekly events hourly. Market pages and integrated audit are supplemental and handle missing data independently.

### Published data contracts

- `fx_macro_raw.json`: dated Trading Economics nominal sovereign yields, policy rate references, indices including DXY, KOSPI, Nikkei and China; OilPrice.com WTI/Brent only; ForexCracked FX and other commodities; FearGreedMeter; FXStreet RSS, and Reuters when accessible.
- `fx_macro_snapshot.json`: metric provenance, issuer and maturity, dated yields and same-tenor spreads, publisher daily changes and strictly sampled source-fetch differences.
- `fx_macro_history.json`: rolling timestamped observations without near-duplicate push-triggered samples.
- `fx_macro_news.json` and `fx_economic_actuals.json`: dated headlines and Forex Factory publisher-reported actuals matched uniquely to scheduled events (not independently confirmed precise release clock).
- `fx_cftc_tff.json`: official CFTC weekly historical leveraged funds, asset managers and dealers; associated historical futures open interest, not intraday CME volume.
- `fx_retail_sentiment.json`: public Myfxbook retail values, minimum 60-minute publisher delay when accessible, explicitly unavailable if site blocks public automation.
- `fx_range_context.json`: ADR20, NY17 context and range reference data derived from completed daily bars, never directional votes.
- `fx_unified_signals.json`: 11-pair provisional technical directions, macro agreement/contradictions, event and source context, range history and invalidation, not executable orders.
- `fx_integrated_audit.json`: source-specific completeness and freshness without conflating collection time with market observation time.

### Strict integrity conditions

Trading Economics public bond values are date-stamped references, not proven intraday quotes. US TIPS is never used in place of nominal Treasury yields. Historical deltas must match identical instruments, source, date, and actual elapsed sample window; suspect extreme changes are rejected until independently corroborated.
OilPrice.com quotes may be delayed. ForexCracked site bid/ask is indicative, not broker-executable. Reuters can block the automated fetch. Myfxbook retail can return 403; OIS and contract-specific CME volume are marked unavailable where unverified. Missing data cannot vote direction.
The options layer and CNN Fear & Greed source are removed. FearGreedMeter is the approved fear/greed source. Alerts remain disabled.

## Locked FOREX MAIN SIGNAL — 15-LAYER MACRO-FIRST AUDIT (user correction Oct 13, 2026)

**This section supersedes the former simplified six-section reading order. NEVER replace it with an abbreviated six-part overview unless the user explicitly requests a change.** For EVERY full FX scan, including any single-pair drilldown, the complete 15-layer source audit is required.

**Exactly match the user's October 13, 2026 full-length audit sample:**
- Timestamped title `FOREX MAIN SIGNAL — 15-LAYER MACRO-FIRST AUDIT`, ET observation time, 11 pairs, closed 15m/30m candles and no API keys; upfront `OVERALL STATUS: PARTIAL/...` with the actual key directional change and explicit collection versus publication times.
- **BEST FIVE TRADING PAIRS FIRST**: compact MOBILE one-line rows `#  PAIR  🟢 BUY / 🔴 SHORT  STAGE  SCORE`. Rank 1–5 with full, unaltered published 50% early + 50% trend technical ordering. Display SELL as **SHORT in red** and BUY **green**. Stage displayed as short `EARLY`, `CONF`, `CONT`, `WAIT`, `CHASE` etc., while the complete updated assessment and unchanged published score remain in JSON/detail. Use nonbreaking spaces in each individual row so words never split (`STRONG` must never wrap its final G). Do not stack columns or wrap a cell over two lines on mobile; prefer shorter labels over squeezing text. When display width is too narrow, permit horizontal scrolling of the intact row rather than splitting individual words.
- **CURRENCY STRENGTH SECOND**: exactly top five strongest in numbered single-line rows `# CCY 🟢 STRONG +score` (neutral grey, weak red), then list other weakest currencies separately so USD/JPY weakness isn't hidden. Source is 11-pair unweighted 15m/30m technical breadth, not an independently measured live strength index. Each strength word MUST remain intact on one line.
- **CRITICAL SETUPS OMITTED FROM TOP FIVE** (any meaningful new directional acceleration/counter-rotation among the other six pairs, with 15m and 30m pips, recorded episode movement, and no invented first/SELL signal).
- Then **each of the fifteen numbered, fully expanded sections, exactly in order**:
  1. Reuters / FXStreet — macro news first (verified headline times, cause, contradictions, do not invent real-time Reuters access).
  2. Economic calendar — released actual/forecast/previous, surprises, verified reaction times versus hypothesis, upcoming events in ET.
  3. Central banks & OIS — all 7 policy references, OIS UNAVAILABLE if missing.
  4. Sovereign nominal bonds — 2Y/5Y/10Y/30Y values by country; matched yield spreads, daily reference versus strict sampled fetch-time changes; NO TIPS contamination.
  5. Commodities — WTI/Brent OilPrice.com ONLY, date/delay; ForexCracked non-crude, iron ore/copper, actual CAD/AUD/NZD implications.
  6. DXY, KOSPI, Nikkei, China, USD/CNH, VIX, FearGreedMeter; mandatory JPY cluster contradiction audit.
  7. CFTC TFF net dealers/asset managers/leveraged positions, **official historical weekly**, change missing unless genuinely sourced.
  8. CME — current live contract OI/volume unavailable unless independently validated; do not substitute CFTC historical OI.
  9. Retail — Myfxbook/Forex Factory/IG/OANDA when available; NEVER invent percentages.
  10. Currency-strength clusters — full seven currency breadth strengths, strongest vs weakest, accelerating/weakening only with supporting proof.
  11. ALL 11 — latest independently inspected **COMPLETED** 15m/30m pair observations, 15m and 30m pips and latest close, with both original published direction and separate updated assessment.
  12. 1H/4H/Daily trend/EMA context (context only, never veto early 15m/30m); include H1 20/50 EMA and H4 10/20.
  13. ATR/ADR and consolidation — latest vs prior observed three-hour windows; ADR20, NY17 used and statistical room; explicit limits on exact origin/squeeze.
  14. Conditional triggers, structural invalidation and execution quality — every pair, **broker spreads/precise entries/stops/TP1/TP2 MISSING unless genuinely independently verified**.
  15. Historical accountability — saved direction, first recorded observation/price, newest completed price, signed pips since first record, false positives/counter-rotations without hindsight rewriting.
- **FULL 15-LAYER COVERAGE AUDIT** status table (each layer VERIFIED/PARTIAL/MISSING with source status).
- **FINAL FOREX MAIN SIGNAL** with strongest emerging pressure, best counter-rotation, strongest published BUY/SELL opportunity, what's extended, key conflicting news, imminent events, EXECUTION: RESEARCH WATCH ONLY.
- Fully preserve 11 pairs, the fixed 50/50 engine rank, no M5 signal votes, no paid keys, options removed, no automatic trading or notifications.

**Published programmatic report:** `fx_scan_report.json` is the full structured audit; **`fx_scan_report.md`** is the complete readable 15-layer user-facing report, created after each `rotation.yml` technical refresh from existing unified, macro, published calendar, CFTC, retail and completed 15m/30m public candle feeds. Separate clocks explicitly: quote publisher times, collector retrieval clocks and unified board publication. No fake synchronized market ticks. Run `python -m unittest -v test_fx_scan_report`; the technical workflow additionally requires exactly fifteen layers, correct heading, 11 technical rows and unchanged published ranking. Never return to the previous six-section layout without explicit user instruction.

### Locked mobile header — approved October 13, 2026

**User explicitly approved:** Best five FX trading pairs FIRST, then strongest five currencies SECOND, both in one-line compact rows. Format must keep **BUY green**, **SHORT red**, **STRONG green**, **WEAK red**; no wrapped/split words such as `STRON` on one line and `G` on the next. Display short stage labels and numeric scores, with full 15-layer audit continuing afterward. Do not revert to earlier strength-first order without an explicit new request.

## Urgent forex news-first policy watch — October 13, 2026

The user correctly identified a **4:45 AM ET BoJ breaking-policy story** as a significant piece of research missing from the 5:06 AM technical scan. Central-bank and macro surprises matter as early drivers of FX. Do not claim the story independently proves the observed price reversal, and never assign a BUY/SELL on headline text alone: the yen may react differently to competing portions of the report.

- New `fx_news_priority.py` independently **refetches the existing approved FXStreet RSS and Reuters currency page** within the approximately five-minute `rotation.yml` technical scan. This is separate from the slower 15-minute macro data collection and does not manufacture new yield samples.
- `fx_news_priority.json` records source availability, UTC headline publication time, UTC first-seen collection time, latency to first capture, policy/economic urgency, JPY cross/currency mappings and **NO VERIFIED PRICE REACTION** until the actual completed M15/M30 candles are inspected. It tags all eleven monitored crosses and flags missing Reuters/FXStreet coverage. The fusion output attaches a `breaking_policy_news` research field to every pair. The full existing 15-layer audit displays the headlines with source gaps within **Layer 1**, while preserving the user-locked mobile compact **Top Five first, currency strength second** presentation.
- **News is a priority in the interpretation**, not an unverified override. When a major BoJ/RBA/Fed/BoE/ECB/RBNZ/BoC headline appears, explicitly examine affected crosses, observed first reaction, subsequent reversal and 15m/30m close evidence; call it a potential catalyst with uncertainty if price reaction was not independently isolated. A stale/blocked publisher must never be treated as no-news confirmation.
- **Source coverage limitation:** The original story was a Bloomberg report subsequently carried by Newsquawk. Those providers are NOT in this user-approved automated source contract. Merely increasing FXStreet/Reuters polling cannot guarantee catching a Bloomberg/Newsquawk exclusive. Ask the user for explicit source expansion before adding those providers. No API keys, orders, external notifications or adjustments to 50/50 technical ranking.
- Run `python -m unittest -v test_fx_news_priority` in CI and every rotation. Test a simulated BoJ story published 08:45 UTC, its priority classification, pair coverage, first-seen clock, missing Reuters status and the absence of directional trades.

## Scheduled economic news radar and central-bank speeches (Oct 13, 2026)

The Oct 13 FXStreet calendar screenshot lists BoJ Governor Ueda speech and highlights a **calendar coverage gap**: our keyless Forex Factory/Fair Economy weekly feed did not include that event. The screenshot calendar clock was about four hours ahead of the user's Eastern device clock. Do not assume the displayed 04:30 is 04:30 Eastern; event dates require an explicit publisher timezone before conversion. Example: if 04:30 UTC is verified, that is **00:30 Eastern Daylight Time**, not 04:30 Eastern. This screenshot alone does not prove the actual release time.

**Calendar source integrity:** `collect_ff_calendar.py` retrieves the existing no-key Forex Factory weekly feed, which is not an exhaustive equivalent of the FXStreet calendar. Do not invent missing speeches or claim to ingest FXStreet's authenticated calendar API. Missing event `NO_VERIFIED_FRESH_CALENDAR_EVENTS` is not the same as `NO_EVENT_OCCURRED`. The new `fx_calendar_priority.py`, running after the news watch on the existing approximately five-minute technical schedule, reads published weekly events and records each event's UTC and IANA America/New_York clocks, relative event window, impact, and affected pairs. BoJ/RBA/Fed/BoE/ECB/BoC/RBNZ speeches and policy minutes receive **HIGH POLICY WATCH** even if the feed calls them low impact. Market-moving CPI/PPI/employment data are also elevated. It distinguishes upcoming, near-release, and retrospectively observed event windows; historical post-event M15 checks do not assert publisher causality, correct advance warning or executable signals.

Outputs `fx_calendar_priority.json`, a `scheduled_event_radar` field on all eleven `fx_unified_signals.json` records, and central-bank schedule/coverage in Layer 2 of `fx_scan_report.md` and `fx_scan_report.json`. The five-minute schedule is a GitHub Actions best-effort target, not a guarantee of a real-time market feed. The visual and narrative contract remains **Top Five trading pairs first; top five currency strength second; all fifteen layers below**. Never change technical signal direction from a scheduled event alone. No orders, notifications, options, five-minute trading signal votes or unapproved new news sources. Run `test_fx_calendar_priority` on CI and workflow.

## User-approved public-source expansion — October 13, 2026

The user **explicitly approved** adding **FX Blue** (backup calendar) and **Newsquawk** (additional breaking-news source). This supersedes the previous restriction to only FXStreet/Reuters news and Forex Factory calendar, but does not authorize any other feed, subscriptions, paywall bypass, new API keys, trades, notifications, or changes in scoring/format.

### Calendar: FX Blue public UTC feed

`fx_approved_public_sources.py:parse_fx_blue` requires the publisher's explicit `Time (UTC)` calendar table; resolves the nearest year only within ten days; preserves impact/title/currency/date and rejects ambiguous date or source timing. `fx_calendar_priority.py` merges these events with the existing Forex Factory calendar and marks source coverage/status for both. The 2026-10-13 **BoJ Governor Ueda speech 04:30 UTC** is a regression test. The running current-event radar intentionally excludes events older than two hours; they are not replayed as fresh opportunities. The source fetch may fail or change its public markup; mark UNAVAILABLE rather than filling in timestamps. FXStreet's authenticated calendar is still NOT INGESTED.

### News: Newsquawk public headlines, DELAYED

`fx_approved_public_sources.py:collect_newsquawk` retrieves up to nine publicly linked relevant articles from `https://www.newsquawk.com/headlines`. It requires the explicit public article `Published ... UTC` timestamp. Newsquawk states that its public web articles are delayed by **at least 20 minutes relative to its live professional feed**. Its professional-feed clock (for example **08:45 UTC** for the BoJ Bloomberg report) must **NOT** be mislabeled as the public first-seen clock (**09:05 UTC** at earliest public page publication). Per-source collector first-seen and publication times are separately stored. `fx_news_priority.py` marks the third approved provider `Newsquawk_public_delayed`, keeps Reuters/FXStreet provider statuses, and continues to treat headline direction as UNDETERMINED until price reaction is inspected.

**Research signal safeguards**: all 11-pair mapping, full 15-layer audit, Top Five-before-strength single-line mobile format, 50/50 technical ranks, no M5 technical votes, no executable prices/positions and no notifications remain unchanged. The public source is potentially delayed or blocked; do not claim it would have prevented a historical missed 4:45 AM entry. Verify with `python -m unittest -v test_fx_approved_public_sources test_fx_news_priority test_fx_calendar_priority` and the scheduled GitHub workflow.

## ACTIVE: Free GitHub four-slot closed-candle schedule — October 13, 2026

The user explicitly selected **free GitHub Actions only**; no Render cron, paid servers, subscriptions or API keys. The previous inactive paid Render configuration and runner have been deleted. Current technical workflow: `.github/workflows/rotation.yml`, schedule `2,17,32,47 * * * *` UTC (the same clock minutes in America/New_York), **4 targeted slots hourly**. Code pushes no longer launch off-slot technical scans; manual dispatch remains available. GitHub's scheduled starts may be delayed or skipped, so the schedule is not an on-time delivery guarantee.

**M15/M30/H1 at each slot:** `fx_github_slot.py collect` retries the public ForexToolkits feed (up to four minutes after the due time), uses `fx_exact_candle_gate.validate` to require the exact latest completed M15/M30/H1 candle closes for **all 11 monitored pairs**, and checks that recent in-market candle sequences have no gaps. Legitimate weekend FX market gaps do not count as missing data. On each :02 target the expected M15/M30/H1 closes are :00/:00/:00; :17 uses :15/:00/:00; :32 uses :30/:30/:00; :47 uses :45/:30/:00. Only the M15 and M30 data may vote BUY/SELL; H1 is longer-timeframe context. M5 is not included.

A validated run executes all existing TradingView, technical structure, currency-cluster, central-bank/headline, economics, 15-layer and 50/50 ranking steps and executes `fx_github_slot.py finalize` before publication. If the job starts beyond the four-minute start tolerance, the provider lacks the exact closing candle, any of the three timeframes has an active-market historical gap, or the full pipeline fails, the workflow **does not overwrite** the previous market data, direction or reports. It does publish `fx_scan_health.json` and `fx_scan_slot_history.json` with UTC due time, actual start, retrieved candle clocks, attempts and failure reason, while marking missed scheduled runs failed in GitHub Actions. Subsequent runs record unobserved scheduled slots as *missing publication records*, never as backfilled historical alerts or first signal time.

**Truthful timing:** An older 30m or 1H close is correct until the next half-hour or hourly candle actually closes. A newly required M15 close cannot be substituted with the preceding M15 candle. Publication success means timestamp-aligned research data, **not** a broker fill, guaranteed low latency or an execution alert. GitHub Actions may still queue or skip slots; no free GitHub-only implementation guarantees four on-time completed runs each hour.

**Hourly ChatGPT full report:** The separate active task still runs hourly at :04 ET; its timing has **not** been changed under this modification. The report must verify the GitHub publication and latest candle time. A report delivered at :04 can still precede a delayed :02 GitHub publication; the proper status is delayed/unavailable, never an actionable old signal. Discuss moving the hourly task to a post-publication time with the user before updating it.

Verification: `python -m unittest -v test_fx_exact_candle_gate test_fx_github_slot` and full GitHub offline CI. A successful push-triggered **6:17 PM EDT setup test on Oct 13, 2026** exercised the complete pipeline using exact candles but is not proof of scheduled cron punctuality. Preflight code-push runs are labeled `trigger_event: push`; only `trigger_event: schedule` proves a scheduled run. A separate `last_successful_scheduled_slot_utc` field makes that distinction visible.
