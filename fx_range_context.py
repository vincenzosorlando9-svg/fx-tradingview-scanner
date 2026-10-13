#!/usr/bin/env python3
"""ADR20, observed session ranges, NY17 rollover and calendar liquidity context.

Uses ONLY completed M15 observations for intraday ranges; D1 *historical*
completed bars provide ADR20 and are never used for an early direction.
Source provider clock must be unambiguously normalized before use.
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PAIRS=("AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY",
       "AUDJPY","NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP")
UTC=timezone.utc
NY=ZoneInfo("America/New_York")
LONDON=ZoneInfo("Europe/London")
TOKYO=ZoneInfo("Asia/Tokyo")

def normalize_clock(source_timestamp, collected):
    if source_timestamp is None or collected is None:
        raise ValueError("upstream_reference_clock_missing")
    delta=float(source_timestamp)-collected.timestamp()
    rounded=round(delta/3600)*3600
    if abs(delta-rounded)>600 or abs(rounded)>43200:
        raise ValueError("upstream_clock_ambiguous")
    return rounded

def validate(f, minutes, offset, now):
    cols=("t","o","h","l","c")
    values=[f.get(k) for k in cols]
    if not all(isinstance(x,list) for x in values) or len({len(x) for x in values})!=1:
        raise ValueError("invalid_ohlc_columns")
    out=[]
    for values in zip(*values):
        try:
            ts,o,h,l,c=map(float,values)
            d=datetime.fromtimestamp(ts-offset, UTC)
            if not all(math.isfinite(x) for x in (o,h,l,c)) or h<max(o,c,l) or l>min(o,c):
                continue
        except (ValueError,TypeError,OverflowError):
            continue
        if d>now+timedelta(minutes=2):
            continue
        closed=d+timedelta(minutes=minutes)<=now if minutes else d<now
        if not closed:
            continue
        out.append({"opened_utc":d,"o":o,"h":h,"l":l,"c":c})
    out.sort(key=lambda x:x["opened_utc"])
    if len({x["opened_utc"] for x in out})!=len(out):
        raise ValueError("duplicate_upstream_candle_times")
    return out

def ny_rollover_start(now):
    n=now.astimezone(NY)
    d=n.date() if n.hour>=17 else n.date()-timedelta(days=1)
    return datetime(d.year,d.month,d.day,17,tzinfo=NY).astimezone(UTC)

def range_for(bars):
    if not bars:
        return None
    return {"high":max(x["h"] for x in bars), "low":min(x["l"] for x in bars),
            "first_observed_open_utc":bars[0]["opened_utc"].isoformat(),
            "last_observed_open_utc":bars[-1]["opened_utc"].isoformat(),
            "closed_15m_bars":len(bars)}

def compute(pair,raw,offset,now):
    out={"pair":pair, "status":"UNAVAILABLE","ADR20_pips":None,
         "ADR20_complete_days":0,"NY17_day_used_pips":None,
         "NY17_ADR_percent_used":None,"ADR_remaining_reference_pips":None,
         "NY17_rollover_start_utc":ny_rollover_start(now).isoformat(),
         "session_ranges":{}, "reference_only":True,
         "used_for_signal_direction":False,
         "note":"Ranges are context only, not trade targets or closed-15m/30m direction"}
    pip=.01 if pair.endswith("JPY") else .0001
    try:
        if not isinstance(raw,dict):
            raise ValueError("pair_unavailable")
        m15=validate((raw.get("tf") or {}).get("M15") or {},15,offset,now)
        # D1 source OHLC timestamps are previous-day rollovers; all bars
        # before this NY17 session must be completed even if provider includes
        # a still-running D1 row at the end.
        d1=validate((raw.get("tf") or {}).get("D1") or {},1440,offset,now)
        daily=[x for x in d1 if x["opened_utc"]<ny_rollover_start(now)]
        completed=daily[-20:]
        if len(completed)==20:
            out["ADR20_pips"]=round(sum((x["h"]-x["l"])/pip for x in completed)/20,2)
            out["ADR20_complete_days"]=len(completed)
        day_start=ny_rollover_start(now)
        # Recent 50 M15 candles cover only 12.5h, less than a complete FX day.
        # A D1 *running* candle is allowed for daily-range context when its
        # source rollover starts at the NY17 clock. It MUST NEVER enter any
        # 15m/30m direction or signal decision.
        today_bars=[x for x in m15 if day_start<=x["opened_utc"]<=now]
        day_high=max((x["h"] for x in today_bars),default=None)
        day_low=min((x["l"] for x in today_bars),default=None)
        out["day_range_completeness"]="PARTIAL_OBSERVED_M15_HISTORY"
        running=(raw.get("tf") or {}).get("D1") or {}
        for raw_ts,o,h,l,c in zip(*(running.get(k,[]) for k in ("t","o","h","l","c"))):
            try:
                open_dt=datetime.fromtimestamp(float(raw_ts)-offset, UTC)
                vals=[float(x) for x in (o,h,l,c)]
                if (abs((open_dt-day_start).total_seconds()) <= 600 and
                    all(math.isfinite(x) for x in vals) and
                    vals[1]>=max(vals[0],vals[2],vals[3]) and
                    vals[2]<=min(vals[0],vals[1],vals[3])):
                    day_high=max([float(h)]+([day_high] if day_high is not None else []))
                    day_low=min([float(l)]+([day_low] if day_low is not None else []))
                    out["day_range_completeness"]="RUNNING_D1_REFERENCE_NY17_ALIGNED"
                    out["D1_current_session_used_for_direction"]=False
            except (TypeError,ValueError,OverflowError):
                continue
        if today_bars:
            out["NY17_day_first_observed_open_utc"]=today_bars[0]["opened_utc"].isoformat()
        if day_high is not None and day_low is not None:
            used=(day_high-day_low)/pip
            out["NY17_day_used_pips"]=round(used,2)
            if out["ADR20_pips"] and out["day_range_completeness"]=="RUNNING_D1_REFERENCE_NY17_ALIGNED":
                out["NY17_ADR_percent_used"]=round(used/out["ADR20_pips"]*100,1)
                out["ADR_remaining_reference_pips"]=round(max(0,out["ADR20_pips"]-used),2)
        # Session hours are clock *windows*, not claims about broker liquidity.
        # The Tokyo session 09:00-18:00 JST, London 08:00-17:00 local,
        # New York 08:00-17:00 ET. Recent 50 M15 bars may be insufficient;
        # only observed closed candles are published.
        sessions={
            "TOKYO":(TOKYO,9,18),
            "LONDON":(LONDON,8,17),
            "NEW_YORK":(NY,8,17),
        }
        for name,(tz,h1,h2) in sessions.items():
            local=now.astimezone(tz)
            candidates=[local.date()-timedelta(days=1),local.date()]
            windows=[]
            for date in candidates:
                start=datetime(date.year,date.month,date.day,h1,tzinfo=tz).astimezone(UTC)
                finish=datetime(date.year,date.month,date.day,h2,tzinfo=tz).astimezone(UTC)
                windows.append((start,finish))
            viable=[(start,end) for start,end in windows if start<=now]
            if not viable:
                continue
            start,end=max(viable,key=lambda v:v[0])
            subset=[x for x in m15 if start<=x["opened_utc"]<end]
            segment=range_for(subset)
            if segment:
                segment["range_pips"]=round((segment["high"]-segment["low"])/pip,2)
                segment["session_start_utc"]=start.isoformat()
                segment["scheduled_session_end_utc"]=end.isoformat()
                segment["session_in_progress"]=now<end
                segment["observed_partial"]=(
                    now<end or
                    subset[0]["opened_utc"]>start+timedelta(minutes=15) or
                    (now>=end and subset[-1]["opened_utc"]<end-timedelta(minutes=15)))
                out["session_ranges"][name]=segment
        out["status"]="COMPLETE_ADR_WITH_PARTIAL_INTRADAY_WINDOW" if out["ADR20_pips"] else "PARTIAL_ADR_UNAVAILABLE"
    except (KeyError,TypeError,ValueError,OverflowError) as e:
        out["error"]=str(e)
    return out

def main():
    now=datetime.now(UTC)
    try:
        vol=json.loads(Path("fx_volatility.json").read_text(encoding="utf-8"))
        source_at=datetime.fromisoformat(vol["collected_at_utc"].replace("Z","+00:00"))
        off=normalize_clock(vol.get("source_timestamp"),source_at)
        age=(now-source_at).total_seconds()/60
        if not -2<=age<=45:
            raise ValueError("upstream_volatility_feed_stale")
        results={p:compute(p,(vol.get("pairs") or {}).get(p),off,now) for p in PAIRS}
        status="OBSERVED_REFERENCE_CONTEXT"
    except (OSError,ValueError,TypeError,KeyError) as e:
        results={p:{"pair":p,"status":"UNAVAILABLE","reason":str(e),
                    "used_for_signal_direction":False} for p in PAIRS}
        status="UNAVAILABLE_UPSTREAM_VOLATILITY"
    obj={"generated_at_utc":now.isoformat(),"source_collected_at_utc":vol.get("collected_at_utc") if status!="UNAVAILABLE_UPSTREAM_VOLATILITY" else None,
         "status":status, "pairs":results,
         "timeframe_contract":"D1_CONTEXT_AND_COMPLETED_M15_RANGES_ONLY_NEVER_SIGNAL",
         "source_upstream_freshness":"NOT_INDEPENDENTLY_VERIFIED"}
    Path("fx_range_context.json").write_text(json.dumps(obj,indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"status":status,"pairs":len(results),
                      "valid_ADR20":sum(x.get("ADR20_pips") is not None for x in results.values())}))

if __name__=="__main__":
    main()
