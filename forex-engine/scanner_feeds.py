"""Validate existing GitHub scanner feeds without treating them as live trade signals."""
import argparse,json,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from quotes import PAIRS

BASE="https://raw.githubusercontent.com/vincenzosorlando9-svg/fx-tradingview-scanner/main/"
FEEDS=("fx_technicals.json","fx_volatility.json")
TIMEFRAMES=("15m","30m","1h","4h")
INDICATORS=("RSI","Stoch.K","Stoch.D","MACD.macd","MACD.signal","ADX","ATR")

def parse_time(value):
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
        return d if d.tzinfo else None
    except (ValueError,TypeError,AttributeError):return None

def check_feed(name,payload,now=None,max_age_seconds=1200):
    now=now or datetime.now(timezone.utc)
    stamp=parse_time(payload.get("collected_at_utc"))
    age=(now-stamp).total_seconds() if stamp else None
    freshness="FRESH" if age is not None and -15<=age<=max_age_seconds else "STALE_OR_UNTIMED"
    pairs=payload.get("pairs",{})
    missing=[p for p in PAIRS if p not in pairs]
    status={"feed":name,"timestamp":payload.get("collected_at_utc"),"age_seconds":round(age,1) if age is not None else None,
            "freshness":freshness,"missing_pairs":missing,"pair_count":len(pairs),"source_observation_verified":False}
    if name=="fx_technicals.json":
        status["indicators_only"]={}
        for pair in PAIRS:
            timeframes=pairs.get(pair,{})
            status["indicators_only"][pair]={}
            for tf in TIMEFRAMES:
                entry=timeframes.get(tf,{})
                indicators=entry.get("indicators",{}) if entry.get("status")=="ok" else {}
                status["indicators_only"][pair][tf]={k:indicators.get(k) for k in INDICATORS}
    elif name=="fx_volatility.json":
        status["provider_pair_count"]=payload.get("provider_pair_count")
        status["volatility_status"]=payload.get("status")
    status["usable_for_live_signals"]=False
    return status

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="scanner_feed_audit.json")
    parser.add_argument("--max-age-seconds",type=int,default=1200)
    args=parser.parse_args()
    results=[]
    for name in FEEDS:
        try:
            req=urllib.request.Request(BASE+name,headers={"User-Agent":"FXAudit/0.3"})
            with urllib.request.urlopen(req,timeout=12) as resp:
                payload=json.load(resp)
            results.append(check_feed(name,payload,max_age_seconds=args.max_age_seconds))
        except Exception as error:
            results.append({"feed":name,"freshness":"UNAVAILABLE","error":str(error),"usable_for_live_signals":False})
    report={"checked_at_utc":datetime.now(timezone.utc).isoformat(),"feeds":results,
            "all_feeds_fresh":all(x.get("freshness")=="FRESH" and not x.get("missing_pairs") for x in results),
            "trading_evidence_gate_pass":False}
    Path(args.output).write_text(json.dumps(report,indent=2))
    print(json.dumps({"checked_at_utc":report["checked_at_utc"],"all_feeds_fresh":report["all_feeds_fresh"],
                      "feed_statuses":[{"feed":x["feed"],"freshness":x["freshness"],"missing_pairs":x.get("missing_pairs")} for x in results]},indent=2))
if __name__=="__main__":main()
