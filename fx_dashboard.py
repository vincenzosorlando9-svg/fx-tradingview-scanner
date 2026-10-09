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
    rows=[]
    for pair in PAIRS:
        r=existing.get(pair,{})
        frames=r.get("timeframes") or {}
        checks={}
        for tf in ("5m","15m","30m","1H"):
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
        candle_ok=all(fresh(checks[tf]["candle_age_min"],{"5m":6,"15m":18,"30m":33}[tf])
                      and not checks[tf]["error"] for tf in ("5m","15m","30m"))
        source_ok=all(fresh(v) for v in ages.values()) and versions_match and candle_ok
        original_direction=r.get("direction","NONE")
        original_stage=r.get("stage","WAIT")
        valid_watch=source_ok and r.get("status")=="WATCH_FOR_ENTRY" and original_direction in ("BUY","SELL")
        row={
            "pair":pair,
            "direction":original_direction if source_ok else "UNVERIFIED",
            "stage":original_stage if source_ok else "UNVERIFIED",
            "entry_readiness":"TECHNICAL_WATCH_ONLY" if valid_watch else "WAIT",
            "raw_detector_direction":original_direction,
            "raw_detector_stage":original_stage,
            "source_valid":source_ok,
            "technical_price_divergence_pips":r.get("price_source_difference_pips"),
            "timeframes":checks,
            "conditional_level_reference_only":(r.get("entry") or {}).get("level"),
            "detector_reasons":r.get("reasons",[]),
            "entry":None,"stop":None,"tp1":None,"tp2":None
        }
        rows.append(row)
    watches=[r for r in rows if r["entry_readiness"]=="TECHNICAL_WATCH_ONLY"]
    watches.sort(key=lambda x:({"EARLY":0,"CONFIRMING":1,"EXTENDED":2}.get(x["stage"],3),x["pair"]))
    # Optional independent sources are reference-only unless their own timestamp is verified.
    try:
        secondary = load("fx_secondary_sources.json")
    except (OSError, ValueError):
        secondary = {"sources":{}, "error":"OPTIONAL_SECONDARY_FILE_UNAVAILABLE"}
    dashboard={
        "generated_at_utc":now.isoformat(),
        "purpose":"TECHNICAL_RESEARCH_ONLY_NOT_AN_EXECUTABLE_TRADE_SIGNAL",
        "data_sources_utc":times,
        "source_age_minutes_at_generation":ages,
        "source_versions_match":versions_match,
        "warnings":warnings,
        "scope":"11 TradingView-covered pairs; EUR/NZD NOT INCLUDED",
        "priority_timeframes":["5m","15m","30m"],
        "max_closed_candle_age_minutes":{"5m":6,"15m":18,"30m":33},
        "freshness_rule":"Any stale primary candle blocks pair from technical watchlist; collection timestamp alone never proves candle freshness.",
        "optional_secondary_sources":secondary,
        "secondary_source_rule":"FXStreet and FXEmpire are reference-only unless a publisher timestamp proves fresh 5m/15m/30m data. No second-opinion ratings can override fresh scanner rotations.",
        "available_technical_watch_count":len(watches),
        "technical_watchlist":[{"pair":r["pair"],"direction":r["direction"],"stage":r["stage"],
            "last_closed_5m_utc":r["timeframes"]["5m"]["last_closed_utc"]} for r in watches],
        "pairs":rows,
        "independent_checks_not_performed":["Reuters/FXStreet news","economic calendar","rates/yields/OIS",
            "cross-pair cluster confirmation","ADR20","fresh bid/ask and spread","CFTC","retail sentiment","options"],
        "reader_instructions":"Check timestamps and source_valid. Compare with independently verified quote, news, yields, currency cross-cluster and ADR before ANY trade recommendation. If missing/stale, say unverified. Never present this watchlist as live Top 3."
    }
    Path("fx_scan_dashboard.json").write_text(json.dumps(dashboard,indent=2),encoding="utf-8")
    print("Dashboard generated:",len(rows),"pairs",len(watches),"fresh technical watches; warnings:",warnings)

if __name__=="__main__":
    main()
