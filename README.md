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

## Locked full FX scan reading order — user-approved October 13, 2026

**DO NOT CHANGE THIS PRESENTATION ORDER without an explicit new instruction from the user.** This supersedes the old `Top 3/news first` display order for the *report*, but not the underlying priority of news gathering or technical signal calculations. Every scan, including a single-pair discussion, must still perform the full-spectrum audit; the displayed full report starts with currency strength.

1. **Current currency strength FIRST:** show *all seven* currencies strongest → weakest, current strength scores, strongest / weakest names, ties, timestamp, acceleration only if independently validated. Existing `currency_strength_breadth` is **unweighted 11-pair closed M15/M30 directional breadth**, NOT an independently verified real-time currency-strength feed. Say so, and show UNAVAILABLE if incomplete.
2. **Best FIVE trading pairs SECOND:** rank 1–5 without altering the established 50% early opportunity / 50% trend strength technical score. Each row: pair, BUY/SELL, EARLY/CONFIRMING/EXTENDED/WAIT, rank score, source-identified price and clock, macro alignment and signal readiness. Never quietly substitute best three.
3. **Detailed setup for EACH of the five THIRD:** WHY NOW?, news catalyst, trigger or conditional entry, invalidation/stop, TP1/TP2, market timestamp, first signal time, 15m/30m timing, H1 EMA20/EMA50 and 4H EMA10/EMA20, ADR/ATR remaining, nearby levels, chase risk, macro agreement/disagreement, and unavailable inputs. Missing or unverified entries, stops, targets must remain null, not fabricated.
4. **Complete market intelligence FOURTH:** Reuters/FXStreet and news timeline; Forex Factory actual/forecast/calendar; central banks and policy rates; 2Y/5Y/10Y/30Y sovereign yields and valid observed changes; OIS when genuinely verified; oil solely OilPrice.com, other commodities and China/CNH; DXY, VIX, Asian/global indices and FearGreedMeter; CFTC/CME/retail positioning; currency clusters, technical indicators, timeframe structures, ADR/session ranges and source freshness. News is still collected and interpreted first internally.
5. **ALL 11 approved pairs FIFTH:** full BUY/SELL/WAIT board including non-top-five pairs, rankings and integrity flags.
6. **Final scan conclusion SIXTH:** strongest actionable *research* setup, earliest emerging rotation, extended/do-not-chase pairs, upcoming catalysts and the specific price/market evidence that could invalidate the thesis.

Permanent output: `fx_scan_report.json` built by `fx_scan_report.py` from the current synchronized `fx_unified_signals.json` + `fx_scan_dashboard.json` and existing macro documents, after each scheduled technical refresh. It has six fixed top-level ordered report sections plus `layout_contract`, carries original all-11 records without changing direction or rank, and is checked by `test_fx_scan_report.py` in both offline CI and technical workflow. No executable broker prices, trading orders, app/email notifications, options layer, API keys, or M5 signals. Format stays locked by default until **the user explicitly changes it**.
