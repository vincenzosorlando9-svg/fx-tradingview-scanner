"""NY 17:00 FX levels from D1 session candles, with explicit partial coverage.
D1 feed timestamps must align with NY 17:00 rollover after source-clock correction.
"""
import json, math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

UTC=timezone.utc
NY=ZoneInfo("America/New_York")
PAIRS=("AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY","NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP")

def session_start(t):
    local=t.astimezone(NY)
    d=local.date() if local.hour>=17 else local.date()-timedelta(days=1)
    return datetime(d.year,d.month,d.day,17,tzinfo=NY).astimezone(UTC)

def week_start(t):
    d=session_start(t).astimezone(NY).date()
    sunday=d-timedelta(days=(d.weekday()+1)%7)
    return datetime(sunday.year,sunday.month,sunday.day,17,tzinfo=NY).astimezone(UTC)

def pivots(h,l,c):
    p=(h+l+c)/3
    return {"P":p,"R1":2*p-l,"S1":2*p-h,"R2":p+(h-l),"S2":p-(h-l),
            "R3":h+2*(p-l),"S3":l-2*(h-p)}

def combine(rows):
    if not rows:return None
    return {"open":rows[0][1],"high":max(x[2] for x in rows),
            "low":min(x[3] for x in rows),"close":rows[-1][4],
            "bars":len(rows),"start_utc":rows[0][0].isoformat(),
            "last_candle_start_utc":rows[-1][0].isoformat()}

def compute(pair,raw,now,offset):
    out={"pair":pair,"status":"UNAVAILABLE","daily_open":None,"current_day":None,
         "previous_day":None,"current_week":None,"previous_week":None,
         "daily_pivots":None,"weekly_pivots":None,"distance_from_daily_open_pips":None,
         "daily_open_behavior":"UNAVAILABLE","reason":None,
         "timezone":"America/New_York","rollover":"17:00 New York"}
    try:
        f=raw["tf"]["D1"]
        arrays=[f[k] for k in ("t","o","h","l","c")]
        if len(arrays[0])<8 or len({len(a) for a in arrays})!=1:
            raise ValueError("missing_or_misaligned_D1")
        rows=[]
        for vals in zip(*arrays):
            ts,o,h,l,c=map(float,vals)
            t=datetime.fromtimestamp(ts-offset,UTC)
            if not all(math.isfinite(v) for v in (o,h,l,c)) or h<max(o,c,l) or l>min(o,c):
                raise ValueError("invalid_D1_ohlc")
            if t>now+timedelta(minutes=10):continue
            rows.append((t,o,h,l,c))
        rows.sort(key=lambda x:x[0])
        if len(set(x[0] for x in rows))!=len(rows):raise ValueError("duplicate_D1")
        ds=session_start(now)
        ws=week_start(now)
        # D1 candles from the provider may use UTC midnight instead of NY 17:00.
        # In that case preserve the daily and weekly high/low as source-calendar references,
        # but never label them NY rollover levels or derive NY pivots.
        alignment=all(abs((x[0]-session_start(x[0])).total_seconds())<600 for x in rows[-8:])
        if not alignment:
            out["reason"]="D1_source_candles_not_aligned_to_NY_17_rollover"
            out["source_daily_latest"]=combine(rows[-1:])
            out["source_previous_daily"]=combine(rows[-2:-1])
            out["source_previous_5_daily"]=combine(rows[-6:-1])
            out["source_daily_calendar"]="PROVIDER_DEFINED_NOT_NY_ROLLOVER"
            return out
        current=[x for x in rows if x[0]==ds]
        prior=[x for x in rows if x[0]<ds]
        if not prior:raise ValueError("no_completed_prior_D1")
        # Last closed D1 may be several elapsed days old over the weekend;
        # only accept the immediately preceding FX trading session.
        prev_start=ds.astimezone(NY).date()-timedelta(days=1)
        if prev_start.weekday()==5:prev_start-=timedelta(days=1)
        if prev_start.weekday()==4:prev_start-=timedelta(days=1)
        expected=datetime(prev_start.year,prev_start.month,prev_start.day,17,tzinfo=NY).astimezone(UTC)
        previous=[x for x in prior if x[0]==expected]
        out["previous_day"]=combine(previous)
        out["current_day"]=combine(current)
        out["daily_open"]=current[0][1] if current else None
        lastweek=[x for x in rows if ws-timedelta(days=7)<=x[0]<ws]
        thisweek=[x for x in rows if ws<=x[0]<=now]
        out["current_week"]=combine(thisweek)
        out["previous_week"]=combine(lastweek) if len(lastweek)>=4 else None
        if previous:
            out["daily_pivots"]=pivots(previous[0][2],previous[0][3],previous[0][4])
        if out["previous_week"]:
            w=out["previous_week"]
            out["weekly_pivots"]=pivots(w["high"],w["low"],w["close"])
        if current:
            pip=.01 if pair.endswith("JPY") else .0001
            delta=(current[0][4]-current[0][1])/pip
            out["distance_from_daily_open_pips"]=round(delta,1)
            out["daily_open_behavior"]="ABOVE" if delta>0 else "BELOW" if delta<0 else "AT_OPEN"
        complete=all(out[k] is not None for k in ("current_day","previous_day","current_week","previous_week"))
        out["status"]="COMPLETE" if complete else "PARTIAL"
        out["reason"]=None if complete else "missing_current_or_completed_session_D1"
    except (KeyError,ValueError,TypeError,OSError,OverflowError) as e:
        out["reason"]=str(e)
    return out

def main():
    now=datetime.now(UTC)
    feed=json.loads(Path("fx_volatility.json").read_text())
    collected=datetime.fromisoformat(feed["collected_at_utc"].replace("Z","+00:00"))
    source_time=feed.get("source_timestamp")
    offset=0
    if source_time is not None:
        delta=float(source_time)-collected.timestamp()
        rounded=round(delta/3600)*3600
        if abs(delta-rounded)>600 or abs(rounded)>43200:
            raise ValueError("ambiguous_upstream_clock")
        offset=rounded
    rows={pair:compute(pair,feed.get("pairs",{}).get(pair,{}),now,offset) for pair in PAIRS}
    output={"generated_at_utc":now.isoformat(),"source_collected_at_utc":feed.get("collected_at_utc"),
            "method":"D1 OHLC; NY17 rollover only when source timestamps independently align; provider-calendar fallback explicitly labeled",
            "source_upstream_freshness":"NOT_INDEPENDENTLY_VERIFIED",
            "status_counts":{s:sum(x["status"]==s for x in rows.values()) for s in ("COMPLETE","PARTIAL","UNAVAILABLE")},
            "pairs":rows}
    Path("fx_daily_weekly_levels.json").write_text(json.dumps(output,indent=2))
    print("Daily/weekly levels:",output["status_counts"])

if __name__=="__main__":main()
