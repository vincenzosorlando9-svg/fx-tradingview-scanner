"""Conservative New York 17:00 FX daily/weekly levels from timestamped M5 bars.
A level is unavailable if the feed does not cover its complete session.
This is technical reference data, not a trade recommendation.
"""
import json, math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
PAIRS = ("AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY","NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP")
M5_SECONDS = 300

def session_start(t):
    local=t.astimezone(NY)
    day=local.date() if local.hour>=17 else local.date()-timedelta(days=1)
    return datetime(day.year,day.month,day.day,17,tzinfo=NY).astimezone(UTC)

def week_start(t):
    d=session_start(t).astimezone(NY).date()
    # Forex week starts Sunday 17:00 New York; Monday-Thursday 17:00 belongs next FX day.
    days=(d.weekday()+1)%7
    sunday=d-timedelta(days=days)
    return datetime(sunday.year,sunday.month,sunday.day,17,tzinfo=NY).astimezone(UTC)

def pivots(h,l,c):
    p=(h+l+c)/3
    return {"P":p,"R1":2*p-l,"S1":2*p-h,"R2":p+(h-l),"S2":p-(h-l),
            "R3":h+2*(p-l),"S3":l-2*(h-p)}

def bucket(bars,start,end,require_complete=True):
    selected=[b for b in bars if start<=b[0]<end]
    if not selected: return None
    if require_complete:
        # Market closure intervals are allowed only during the weekend.
        expected=int((end-start).total_seconds()/300)
        if len(selected)!=expected: return None
        if selected[0][0]!=start or selected[-1][0]!=end-timedelta(minutes=5): return None
    return {"open":selected[0][1],"high":max(b[2] for b in selected),
            "low":min(b[3] for b in selected),"close":selected[-1][4],
            "bars":len(selected),"start_utc":start.isoformat(),"end_utc":end.isoformat()}

def compute(pair,raw,now,offset=0):
    result={"pair":pair,"status":"UNAVAILABLE","daily_open":None,
            "current_day":None,"previous_day":None,"current_week":None,
            "previous_week":None,"daily_pivots":None,"weekly_pivots":None,
            "distance_from_daily_open_pips":None,"daily_open_behavior":"UNAVAILABLE",
            "reason":None,"timezone":"America/New_York","rollover":"17:00 New York"}
    try:
        f=raw["tf"]["M5"]; arrays=[f[k] for k in ("t","o","h","l","c")]
        n=len(arrays[0])
        if n<2 or any(len(a)!=n for a in arrays): raise ValueError("missing_or_misaligned_m5")
        bars=[]
        for vals in zip(*arrays):
            ts,o,h,l,c=map(float,vals)
            t=datetime.fromtimestamp(ts-offset,UTC)
            if not all(math.isfinite(v) for v in (o,h,l,c)) or h<max(o,c,l) or l>min(o,c):
                raise ValueError("invalid_ohlc")
            if t+timedelta(minutes=5)<=now+timedelta(seconds=30):
                bars.append((t,o,h,l,c))
        bars.sort(key=lambda b:b[0])
        if len({b[0] for b in bars})!=len(bars): raise ValueError("duplicate_timestamps")
        if not bars or (now-(bars[-1][0]+timedelta(minutes=5))).total_seconds()>600:
            raise ValueError("stale_m5")
        # Session dates determined by NY 17:00, not UTC midnight.
        ds=session_start(now)
        ws=week_start(now)
        prev_ds=ds-timedelta(days=1)
        prev_ws=ws-timedelta(days=7)
        # Current partial buckets need exact first candle and continuity.
        def partial(start):
            end=bars[-1][0]+timedelta(minutes=5)
            if end<=start:return None
            return bucket(bars,start,end,True)
        current_day=partial(ds)
        current_week=partial(ws)
        previous_day=bucket(bars,prev_ds,ds)
        previous_week=bucket(bars,prev_ws,ws)
        result.update(current_day=current_day,previous_day=previous_day,
                      current_week=current_week,previous_week=previous_week)
        if current_day:
            result["daily_open"]=current_day["open"]
            pip=.01 if pair.endswith("JPY") else .0001
            delta=(bars[-1][4]-current_day["open"])/pip
            result["distance_from_daily_open_pips"]=round(delta,1)
            result["daily_open_behavior"]=("ABOVE" if delta>0 else "BELOW" if delta<0 else "AT_OPEN")
        if previous_day:
            result["daily_pivots"]=pivots(previous_day["high"],previous_day["low"],previous_day["close"])
        if previous_week:
            result["weekly_pivots"]=pivots(previous_week["high"],previous_week["low"],previous_week["close"])
        complete=all(result[k] is not None for k in ("current_day","previous_day","current_week","previous_week"))
        result["status"]="COMPLETE" if complete else ("PARTIAL" if current_day else "UNAVAILABLE")
        result["reason"]=None if complete else "insufficient_contiguous_M5_history_for_NY_sessions"
    except (KeyError,TypeError,ValueError,OverflowError,OSError) as exc:
        result["reason"]=str(exc)
    return result

def main():
    now=datetime.now(UTC)
    feed=json.loads(Path("fx_volatility.json").read_text())
    source_time=feed.get("source_timestamp")
    collected=datetime.fromisoformat(feed["collected_at_utc"].replace("Z","+00:00"))
    offset=0
    if source_time is not None:
        delta=float(source_time)-collected.timestamp()
        rounded=round(delta/3600)*3600
        if abs(delta-rounded)>600 or abs(rounded)>43200:
            raise ValueError("Ambiguous upstream clock; refusing to calculate session levels")
        offset=rounded
    rows={pair:compute(pair,feed.get("pairs",{}).get(pair,{}),now,offset) for pair in PAIRS}
    output={"generated_at_utc":now.isoformat(),"source_collected_at_utc":feed.get("collected_at_utc"),
            "method":"contiguous closed M5 OHLC, New York 17:00 session; never infer missing bars",
            "source_upstream_freshness":"NOT_INDEPENDENTLY_VERIFIED",
            "status_counts":{s:sum(v["status"]==s for v in rows.values()) for s in ("COMPLETE","PARTIAL","UNAVAILABLE")},
            "pairs":rows}
    Path("fx_daily_weekly_levels.json").write_text(json.dumps(output,indent=2))
    print("Daily/weekly levels:",output["status_counts"])

if __name__=="__main__":
    main()
