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
8. **Positioning:** CFTC TFF, CME open interest/volume, options if available, OANDA/IG/Myfxbook/A1Trading retail positioning, CNN Fear & Greed and FearGreedMeter.
9. **Technical timing LAST:** fresh 15m + 30m alignment for EARLY; 1H price vs EMA20 for confirmation, EMA50 for added strength; 4H EMA10 closed-candle cross, EMA20 trend context, resistance rejection, failed breakouts and measured consolidation duration; Daily background. Check HH/HL/LH/LL, EMAs, RSI/MACD, ATR/ADR used and remaining range, nearby levels and chase risk. Do not use 5m as a detector input.
10. **Execution board:** Top 3 pair / BUY-SELL / EARLY-CONFIRMING-EXTENDED / verified price and timestamp / conditional entry / invalidation or stop / TP1 and TP2 when grounded. Target 20–30 intraday pips; don't chase mature moves. Identify news-driven risks and macro/technical disagreement.

### Accuracy and integrity rules

- A directional chart candidate is **not** a macro-confirmed trade. Classify catalysts as VERIFIED, SUPPORTING, HYPOTHESIS or UNAVAILABLE, with source and observation timestamp.
- When commodity moves oppose the technical direction, flag **COMMODITY_DIVERGENCE**; when rate differentials oppose it, flag **YIELD_DIVERGENCE**. Neither is an automatic veto.
- No invented live prices, yields, probabilities, spreads, sentiment, stops or targets. Mark missing or stale sources **UNAVAILABLE**.
- GitHub technical/volatility JSON feeds must be fresh and timestamp-checked; upstream freshness is not implied by a new local file.
- **This repository currently automates technical data only.** The complete macro audit above is a mandatory research specification, **not a claim that Reuters, yields, OIS, commodities, positioning or calendars are already collected automatically**. Do not label any candidate MACRO_CONFIRMED until the required evidence is actually collected and checked.
- Backtest signal detection without future leakage and compare calculated 4H closed-candle EMA/crossover values to TradingView before claiming trading accuracy.

### No-API-key macro collection contract (2026-10-12)

- **No paid or secret API keys required.** Do not require `TE_API_KEY` or fail the macro collection job because that variable is absent.
- Trading Economics **public bond pages** are the primary *human-readable research source*, not a guaranteed programmatic API. If access is blocked or content is stale, attempt publicly accessible Investing.com, FT, or official treasury/central-bank releases; retain source URL, market date, collection time, maturity and value.
- OIS / policy-implied rate expectations are a separate field from sovereign yields. Never substitute 2Y/5Y/10Y/30Y yields for OIS; label OIS `UNAVAILABLE` if no verifiable public observation exists.
- Collect available data independently per country and maturity. A missing field must not abort the remaining 11-pair technical scan. Use `VERIFIED`, `PARTIAL` and `MISSING` honestly; no invented or stale-as-current values.
- Verify actual GitHub publication time separately from upstream observation time. Preserve the existing technical feeds and scheduled runs.
- **Implementation status:** This is a data-collection requirement, not proof that a no-key macro collector is installed or running. The macro workflow must be identified, patched and tested before declaring the error fixed.
