# FOREX MAIN SIGNAL — audit-only prototype

This folder is isolated from the original scanner. It **does not generate trading signals**.

## What it does
- Attempts each endpoint in `sources.json` and records retrieval results and Eastern/UTC attempt times.
- Emits `latest_report.json` and a local SQLite audit file.
- Records no source observation timestamps unless independently parsed (not implemented).
- Keeps `analysis_allowed=false` and `trading_evidence_gate_pass=false` on every run.

## Run
```bash
cd forex-engine
python engine.py --timeout 10 --concurrency 8
```

## Render configuration (NOT deployed until separately configured)
- Runtime: Python 3.11+
- Build: `python -m compileall -q forex-engine/engine.py`
- Start: `python forex-engine/engine.py --database /tmp/fx-audit.sqlite3 --output /tmp/fx-latest-report.json`
- Cron: `0 * * * *` (UTC, hourly; **does not** implement Eastern market quiet hours).
- WARNING: /tmp is ephemeral on Render. Production history requires persistent database and backups.

## Blockers to production
1. The 73 endpoints are **candidate URLs**, not a fully reconciled historical registry; some are homepages, not data feeds.
2. HTTP response does **not** prove data was extracted, current, legal to scrape or accurate.
3. No 11-pair price parsing, 15-layer analysis, verified source observation timestamps, spreads, or signal history.
4. No official-source publication-frequency handling, independent quote validation or market-hours scheduling.
5. A scheduled audit needs persistent external storage to preserve reports. Do not infer completeness from an ephemeral /tmp report.
6. Respect publisher terms and use licensed APIs where necessary. WTI/Brent must only use OilPrice.com.

## Safety
This prototype never produces executable entries, rankings, targets, or recommendations. Missing sources and unavailable data must be logged, not invented.
