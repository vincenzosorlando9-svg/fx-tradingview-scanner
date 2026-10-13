"""Audited, compact integration file for FX Rotation Watch.

Technical watchlist only; NOT a live executable trade signal.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
MAX_AGE_MIN = 25
PAIRS = ("AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY","NZDJPY",
         "EURJPY","EURCAD","USDCAD","EURGBP")

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def parse(s):
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(UTC)
    except (TypeError, ValueError, AttributeError):
        return None

def elapsed(now, timestamp):
    d = parse(timestamp)
    return round((now-d).total_seconds()/60,1) if d else None

def fresh(minutes, maximum=MAX_AGE_MIN):
    return minutes is not None and -3 <= minutes <= maximum

def main():
    now = datetime.now(UTC)
    tv, candles, rotation = [load(s) for s in ("fx_technicals.json","fx_volatility.json","fx_rotation_signals.json")]
    times = {
        "tradingview":tv.get("collected_at_utc"),
        "forextoolkits":candles.get("collected_at_utc"),
        "rotation":rotation.get("generated_at_utc")
    }
    ages = {k:elapsed(now,v) for k,v in times.items()}
    versions_match = (rotation.get("technical_source_utc")==times["tradingview"]
                      and rotation.get("volatility_source_utc")==times["forextoolkits"])
    warnings=[]
    for key,minutes in ages.items():
        if not fresh(minutes):
            warnings.append("STALE_OR_FUTURE_"+key.upper())
    if not versions_match:
        warnings.append("ROTATION_SOURCE_VERSIONS_DO_NOT_MATCH")
    warnings.append("FOREXTOOLKITS_UPSTREAM_FRESHNESS_NOT_INDEPENDENTLY_VERIFIED")

    existing = {r.get("pair"):r for r in rotation.get("pairs",[])}
    levels_path=Path("fx_daily_weekly_levels.json")
    levels=load(levels_path) if levels_path.exists() else {"pairs":{},"status_counts":{},"generated_at_utc":None}
    rows=[]
    for pair in PAIRS:
        r=existing.get(pair,{})
        frames=r.get("timeframes") or {}
        checks={}
        for tf in ("15m","30m","1H","4H","1D"):
            data=frames.get(tf) or {}
            bar=data.get("candles") or {}
            ts=bar.get("last_closed_candle_utc")
            checks[tf]={
                "last_closed_utc":ts,
                "candle_age_min":elapsed(now,ts),
                "error":data.get("error"),
                "atr5_pips":bar.get("atr5_pips"),
                "atr14_pips":bar.get("atr14_pips"),
                "momentum_3bars_pips":bar.get("momentum_3_bars_pips"),
                "structure":bar.get("structure")
            }
        candle_ok=all(fresh(checks[tf]["candle_age_min"],{"15m":18,"30m":33}[tf])
                      and not checks[tf]["error"] for tf in ("15m","30m"))
        htf_ok=all(checks[tf]["last_closed_utc"] is not None and not checks[tf]["error"]
                   and fresh(checks[tf]["candle_age_min"], {"4H":300,"1D":4500}[tf])
                   for tf in ("4H","1D"))
        source_ok=all(fresh(v) for v in ages.values()) and versions_match and candle_ok
        full_context_ok=source_ok and htf_ok
        original_direction=r.get("direction","NONE")
        original_stage=r.get("stage","WAIT")
        valid_watch=source_ok and r.get("status")=="WATCH_FOR_ENTRY" and original_direction in ("BUY","SELL")
        row={
            "pair":pair,
            "daily_weekly_levels":levels.get("pairs",{}).get(pair,{"status":"UNAVAILABLE","reason":"levels_not_generated"}),
            "trade_type":r.get("trade_type","HIGHER_TIMEFRAME_UNVERIFIED"),
            "higher_timeframe_valid":htf_ok,
            "full_context_valid":full_context_ok,
            "direction_score":r.get("direction_score"),
            "move_maturity":r.get("move_maturity"),
            "last_closed_15m_price":((frames.get("15m") or {}).get("candles") or {}).get("closed_price"),
            "higher_timeframe":r.get("higher_timeframe",{}),
            "higher_timeframe_indicators":{tf:(frames.get(tf) or {}).get("technical") for tf in ("1H","4H","1D")},
            "direction":original_direction if source_ok else "UNVERIFIED",
            "stage":original_stage if source_ok else "UNVERIFIED",
            "entry_readiness":"TECHNICAL_WATCH_ONLY" if valid_watch else ("DATA_UNAVAILABLE" if not source_ok or r.get("status")=="DATA_UNAVAILABLE" else r.get("status","NO_TRADE")),
            "setup_status":r.get("status","UNVERIFIED"),
            "raw_detector_direction":original_direction,
            "raw_detector_stage":original_stage,
            "directional_bias":original_direction if source_ok else "UNVERIFIED",
            "source_valid":source_ok,
            "technical_price_divergence_pips":r.get("price_source_difference_pips"),
            "move_origin_proxy":r.get("move_origin_proxy"),
            "timeframes":checks,
            "conditional_level_reference_only":(r.get("entry") or {}).get("level"),
            "detector_reasons":r.get("reasons",[]),
            "entry":None,"stop":None,"tp1":None,"tp2":None
        }
        rows.append(row)
    watches=[r for r in rows if r["entry_readiness"]=="TECHNICAL_WATCH_ONLY"]
    watches.sort(key=lambda x:({"EARLY":0,"CONFIRMING":1,"CONTINUATION":2,"EXTENDED":3}.get(x["stage"],3),x["pair"]))
    # Ranked technical research candidates only; macro confirmation remains external.
    def candidate_rank(row):
        m15 = row["timeframes"]["15m"]
        atr = m15.get("atr14_pips") or 0
        momentum = abs(m15.get("momentum_3bars_pips") or 0)
        stage = {"EARLY": 3, "CONFIRMING": 2, "CONTINUATION": 1, "EXTENDED": 0}.get(row["stage"], 0)
        trend = 1 if row["trade_type"] == "TREND_CONTINUATION" else 0
        return (0.5 * (stage / 3) + 0.5 * (min((row.get("direction_score") or 0) / 11, 1) * 0.65 + trend * 0.35), min(momentum / max(atr, 0.01), 2))
    top_five = sorted(watches, key=candidate_rank, reverse=True)[:5]
    # Directional breadth: a currency receives +1 when base rises or quote falls.
    strength = {}
    for row in rows:
        if not row["source_valid"] or row["direction"] not in ("BUY","SELL"): continue
        base, quote = row["pair"][:3], row["pair"][3:]
        sign = 1 if row["direction"] == "BUY" else -1
        strength[base] = strength.get(base,0) + sign
        strength[quote] = strength.get(quote,0) - sign
    dashboard={
        "currency_strength_breadth":dict(sorted(strength.items(),key=lambda x:-x[1])),
        "currency_strength_note":"Unweighted breadth across fresh directional 11-pair candidates, not an independent live currency strength index",
        "generated_at_utc":now.isoformat(),
        "purpose":"TECHNICAL_RESEARCH_ONLY_NOT_AN_EXECUTABLE_TRADE_SIGNAL",
        "daily_weekly_levels_generated_at_utc":levels.get("generated_at_utc"),
        "daily_weekly_levels_status_counts":levels.get("status_counts",{}),
        "data_sources_utc":times,
        "source_age_minutes_at_generation":ages,
        "source_versions_match":versions_match,
        "warnings":warnings,
        "scope":"11 TradingView-covered pairs; EUR/NZD NOT INCLUDED",
        "higher_timeframe_rule":"Daily and 4H are context, not a veto on early 15m directional watches; countertrend is not reversal",
        "priority_timeframes":["15m","30m","1H","4H","1D"],
        "max_closed_candle_age_minutes":{"15m":18,"30m":33,"1H":75,"4H":300,"1D":4500},
        "signal_timeframes":["15m","30m"],
        "longer_context_timeframes":["1H","4H"],
        "excluded_from_signal_and_ranking":["5m"],
        "freshness_rule":"Any stale primary candle blocks pair from technical watchlist; collection timestamp alone never proves candle freshness.",
        "available_technical_watch_count":len(watches),
        "top_five_technical_candidates":[{"rank":i+1,"pair":r["pair"],
            "direction":r["direction"],"stage":r["stage"],
            "trade_type":r["trade_type"],"direction_score":r.get("direction_score"),"entry_readiness":r["entry_readiness"],
            "move_origin_proxy":r.get("move_origin_proxy"),
            "conditional_level_reference_only":r["conditional_level_reference_only"]}
            for i,r in enumerate(top_five)],
        "top_five_note":"Up to five verified technical watches; macro and executable-price validation still required.",
        "technical_watchlist":[{"pair":r["pair"],"direction":r["direction"],"stage":r["stage"],"trade_type":r["trade_type"],"setup_status":r["setup_status"],
            "last_closed_15m_utc":r["timeframes"]["15m"]["last_closed_utc"]} for r in watches],
        "pairs":rows,
        "independent_checks_not_performed":["approved Trading Economics macro/event verification","economic calendar","rates/yields/OIS",
            "cross-pair cluster confirmation","ADR20","fresh bid/ask and spread","CFTC","retail sentiment"],
        "external_news_and_macro_status":"NOT_COLLECTED_BY_GITHUB_SCANNER_REQUIRES_FULL_REPORT_AUDIT",
        "reader_instructions":"Check timestamps and source_valid. Compare with independently verified quote, news, yields, currency cross-cluster and ADR before ANY trade recommendation. If missing/stale, say unverified. Never present this watchlist as live Top 3."
    }
    Path("fx_scan_dashboard.json").write_text(json.dumps(dashboard,indent=2),encoding="utf-8")
    print("Dashboard generated:",len(rows),"pairs",len(watches),"fresh technical watches; warnings:",warnings)

if __name__=="__main__":
    main()
