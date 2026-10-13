#!/usr/bin/env python3
"""Closed-candle early FX opportunity watches. Research only, never trade orders.

The independent M5 pressure gate is deliberately a WATCH, not an executable
signal. An M15 close upgrades it. Never use future bars in historical replay.
"""
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PAIRS=("AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY","NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP")
JPY=("AUDJPY","NZDJPY","EURJPY","USDJPY")
TIMEFRAME={"M5":300,"M15":900,"M30":1800,"H1":3600,"H4":14400,"D1":86400}
UTC=timezone.utc
ET=ZoneInfo("America/New_York")

def load(name):
    try: return json.loads(Path(name).read_text(encoding="utf-8"))
    except (OSError,ValueError): return None

def parse(value):
    try: return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(UTC)
    except (ValueError,TypeError,AttributeError): return None

def pip(pair):
    return .01 if pair.endswith("JPY") else .0001

def server_offset(vol):
    """Correct whole-hour broker timezone offset or explicitly refuse."""
    stamp=vol.get("source_timestamp")
    collected=parse(vol.get("collected_at_utc"))
    if not isinstance(stamp,(int,float)) or not collected: return None
    raw=float(stamp)-collected.timestamp()
    correction=round(raw/3600)*3600
    if abs(raw-correction)>600 or abs(correction)>43200: return None
    return correction

def closed_bars(frame, tf, at, offset):
    """Only bars whose scheduled close is <= 'at' can influence a decision."""
    if not isinstance(frame,dict): return []
    keys=("t","o","h","l","c")
    if not all(isinstance(frame.get(k),list) for k in keys): return []
    count=len(frame["t"])
    if count<5 or any(len(frame[k])!=count for k in keys): return []
    result=[]
    for i in range(count):
        try:
            start=datetime.fromtimestamp(float(frame["t"][i])-offset,UTC)
            values={k:float(frame[k][i]) for k in ("o","h","l","c")}
        except (TypeError,ValueError,OSError,OverflowError): return []
        if not all(math.isfinite(v) for v in values.values()): return []
        if values["h"]<max(values["o"],values["c"],values["l"]) or values["l"]>min(values["o"],values["c"]): return []
        close=start+timedelta(seconds=TIMEFRAME[tf])
        if close<=at:
            result.append(dict(values,open_utc=start.isoformat(),close_utc=close.isoformat(),close_dt=close))
    return result

def is_quiet(at):
    day=at.astimezone(ET).weekday()  # Friday 4, Saturday 5, Sunday 6
    hour=at.astimezone(ET).hour+at.astimezone(ET).minute/60
    return (day==4 and hour>=14) or day==5 or (day==6 and hour<18)

def event_checks(pair,calendar,at):
    if not isinstance(calendar,dict): return ("MISSING",[])
    collected=parse(calendar.get("collected_at_utc"))
    status="FRESH" if collected and timedelta(0)<=at-collected<=timedelta(hours=3) else "STALE"
    relevant={pair[:3],pair[3:]}
    if "AUD" in relevant or "NZD" in relevant: relevant.add("CNY")
    events=[]
    if status=="FRESH":
        for e in calendar.get("pairs",{}).get(pair,[]):
            when=parse(e.get("event_at_utc"))
            if when and -timedelta(minutes=15)<=when-at<=timedelta(hours=24):
                events.append({"currency":e.get("currency"),"title":e.get("title"),
                               "at_utc":when.isoformat(),"impact":e.get("impact"),
                               "forecast":e.get("forecast"),"previous":e.get("previous"),
                               "actual":e.get("actual"),"post_release_unverified":e.get("actual") is None and when<=at})
        # Be explicit that pair calendar completeness is not independently checked.
    return status,sorted(events,key=lambda e:e["at_utc"])

def pair_bars(vol,pair,at,offset):
    tf=((vol.get("pairs") or {}).get(pair) or {}).get("tf") or {}
    return {k:closed_bars(tf.get(k),k,at,offset) for k in ("M5","M15","M30","H1","H4","D1")}

def currency_cluster(vol,at,offset):
    """JPY buying breadth: each JPY cross down since preceding M15 close."""
    detail={}
    for pair in JPY:
        candles=pair_bars(vol,pair,at,offset)
        m5,m15=candles["M5"],candles["M15"]
        if len(m5)<2 or len(m15)<2:
            detail[pair]={"direction":"UNAVAILABLE"};continue
        # As soon as M15 closes, compare with preceding M15, otherwise use
        # latest CLOSED M5 against last CLOSED M15. Neither uses future prices.
        latest_m15_close=m15[-1]["close_dt"]
        just_closed=timedelta(0)<=at-latest_m15_close<=timedelta(minutes=3)
        first=m15[-2]["c"] if just_closed else m15[-1]["c"]
        last=m15[-1]["c"] if just_closed else m5[-1]["c"]
        movement=round((last-first)/pip(pair),2)
        detail[pair]={"direction":"JPY_STRENGTH" if movement<=-0.5 else
                      "JPY_WEAKNESS" if movement>=0.5 else "NEUTRAL",
                      "move_pips":movement,
                      "reference_kind":"M15_CLOSE" if just_closed else "M5_VS_LAST_M15",
                      "last_close_utc":m15[-1]["close_utc"] if just_closed else m5[-1]["close_utc"]}
    down=sum(v["direction"]=="JPY_STRENGTH" for v in detail.values())
    valid=sum(v["direction"]!="UNAVAILABLE" for v in detail.values())
    return {"jpy_strength_crosses":down,"covered_crosses":valid,
            "status":"BROAD_JPY_STRENGTH" if down>=3 and valid==4 else
                     "PARTIAL_JPY_STRENGTH" if down>=2 else "NO_BROAD_JPY_STRENGTH",
            "pairs":detail}

def directional_pressure(pair, data):
    """Price-structure rotation on CLOSED 15m and 30m candles, no break required.

    This is evidence of deteriorating trend, not verified sell/buy execution.
    The detector examines all 11 pairs symmetrically, not tuned to USD/CAD.
    """
    m15,m30,m5=data["M15"],data["M30"],data["M5"]
    if len(m15)<9 or len(m30)<3 or len(m5)<3:
        return {"status":"INSUFFICIENT_DATA","direction":"NONE","score":0}
    pp=pip(pair)
    recent=m15[-4:]; earlier=m15[-8:-4]
    old_high=max(x["h"] for x in earlier)
    old_low=min(x["l"] for x in earlier)
    new_high=max(x["h"] for x in recent)
    new_low=min(x["l"] for x in recent)
    high_shift=(new_high-old_high)/pp
    low_shift=(new_low-old_low)/pp
    change_15m=(m15[-1]["c"]-m15[-5]["c"])/pp
    change_30m=(m30[-1]["c"]-m30[-3]["c"])/pp
    # Scale noise tolerance with average true range. 0.5pip is the minimum.
    sample=m15[-min(len(m15),15):]
    tr=[max(x["h"]-x["l"],abs(x["h"]-sample[i-1]["c"]),
            abs(x["l"]-sample[i-1]["c"]))/pp for i,x in enumerate(sample) if i>0]
    atr=sum(tr)/len(tr) if tr else 0.0
    threshold=max(.5,.12*atr)
    down={
        "FOUR_BAR_LOWER_HIGHS": high_shift<=-threshold+1e-8,
        "FOUR_BAR_LOWER_LOWS": low_shift<=-threshold+1e-8,
        "FOUR_BAR_NEGATIVE_M15_CLOSE": change_15m<=-threshold+1e-8,
        "TWO_BAR_NEGATIVE_M30_CLOSE": change_30m<=-threshold+1e-8,
    }
    up={
        "FOUR_BAR_HIGHER_LOWS": low_shift>=threshold-1e-8,
        "FOUR_BAR_HIGHER_HIGHS": high_shift>=threshold-1e-8,
        "FOUR_BAR_POSITIVE_M15_CLOSE": change_15m>=threshold-1e-8,
        "TWO_BAR_POSITIVE_M30_CLOSE": change_30m>=threshold-1e-8,
    }
    n_down=sum(down.values()); n_up=sum(up.values())
    direction=("SELL" if n_down>=3 and n_down>=n_up+2 else
               "BUY" if n_up>=3 and n_up>=n_down+2 else "NONE")
    # An opposing last M5 candle is normal near a turning point. Report it;
    # don't veto the earlier directional WATCH or falsely call it confirmed.
    last_m5_change=(m5[-1]["c"]-m5[-2]["c"])/pp
    return {
        "status":"OBSERVED_CLOSED_CANDLES","direction":direction,
        "score":max(n_down,n_up),"sell_evidence":n_down,"buy_evidence":n_up,
        "evidence":[k for k,v in (down if direction=="SELL" else up if direction=="BUY" else {}).items() if v],
        "threshold_pips":round(threshold,2),"recent_m15_atr_pips":round(atr,2),
        "high_shift_pips":round(high_shift,2),
        "low_shift_pips":round(low_shift,2),
        "four_bar_m15_change_pips":round(change_15m,2),
        "two_bar_m30_change_pips":round(change_30m,2),
        "last_closed_m5_change_pips":round(last_m5_change,2),
        "last_m5_conflicts":(direction=="SELL" and last_m5_change>0) or
                             (direction=="BUY" and last_m5_change<0),
        "invalidation_reference":max(old_high,new_high) if direction=="SELL" else
                                  min(old_low,new_low) if direction=="BUY" else None,
        "no_breakout_required":True,
        "caution":"EARLY_DIRECTION_ONLY_NOT_CONFIRMED_EXECUTION"
    }

def detect_pair(pair,vol,at,offset,cluster,calendar=None):
    data=pair_bars(vol,pair,at,offset)
    m5,m15=data["M5"],data["M15"]
    pressure=directional_pressure(pair,data)
    base={"pair":pair,"observation_at_utc":at.isoformat(),
          "direction":"NONE","stage":"WAIT","execution_allowed":False,
          "entry":None,"stop":None,"tp1":None,"tp2":None,
          "outcome_target_pips":[40,50],
          "target_status":"ASPIRATIONAL_NOT_VERIFIED_OPEN_ROOM",
          "source":"FOREXTOOLKITS_CLOSED_OHLC_UPSTREAM_FRESHNESS_UNVERIFIED",
          "status":"PARTIAL_TECHNICAL_RESEARCH_ONLY"}
    cal_status,events=event_checks(pair,calendar,at)
    base["calendar_status"]=cal_status
    base["upcoming_events"]=events
    base["event_within_120_min"]=any(0<= (parse(e["at_utc"])-at).total_seconds()<=7200 for e in events)
    if len(m5)<7 or len(m15)<9:
        return dict(base,reason="INSUFFICIENT_CLOSED_HISTORY")
    if (at-m5[-1]["close_dt"])>timedelta(minutes=10) or (at-m15[-1]["close_dt"])>timedelta(minutes=20):
        return dict(base,reason="STALE_CLOSED_CANDLES")
    # If latest M15 just closed, compare that M15 against the preceding four.
    # Otherwise use the four M15 candles that have closed so far.
    just_closed=timedelta(0)<=at-m15[-1]["close_dt"]<=timedelta(minutes=3)
    reference=m15[-5:-1] if just_closed else m15[-4:]
    if len(reference)!=4:return dict(base,reason="NO_FOUR_BAR_REFERENCE")
    high=max(b["h"] for b in reference)
    low=min(b["l"] for b in reference)
    width=(high-low)/pip(pair)
    previous=m15[-9:-5] if just_closed else m15[-8:-4]
    baseline=((max(b["h"] for b in previous)-min(b["l"] for b in previous))/pip(pair)
              if len(previous)==4 else None)
    # Compression is an *observed four-bar window*, not an inferred range origin.
    compression=baseline is not None and baseline>0 and width<=.75*baseline
    m5current=m5[-1]; m5prev=m5[-2]
    last15=m15[-1]
    m5_down=m5current["c"]<low and m5current["c"]<m5prev["c"]
    m5_up=m5current["c"]>high and m5current["c"]>m5prev["c"]
    m15_down=just_closed and last15["c"]<low and last15["c"]<m15[-2]["c"]
    m15_up=just_closed and last15["c"]>high and last15["c"]>m15[-2]["c"]
    pressure_down=(m5current["c"]<m5prev["c"] and
                   m5current["c"]<(m15[-2]["c"] if just_closed else m15[-1]["c"]) and
                   m5current["c"] <=low+.25*(high-low))
    pressure_up=(m5current["c"]>m5prev["c"] and
                 m5current["c"]>(m15[-2]["c"] if just_closed else m15[-1]["c"]) and
                 m5current["c"]>=high-.25*(high-low))
    # A reversal/rotation need not break a boundary. Favor four independent
    # price-structure observations over one late EMA or M5 counterbounce.
    pressure_dir=pressure.get("direction","NONE")
    if pressure_dir in ("BUY","SELL"): direction=pressure_dir
    elif m15_down or m5_down: direction="SELL"
    elif m15_up or m5_up: direction="BUY"
    elif pair in JPY and cluster.get("status")=="BROAD_JPY_STRENGTH" and pressure_down:
        direction="SELL"
    elif pair in JPY and cluster.get("status")=="NO_BROAD_JPY_STRENGTH" and pressure_up:
        direction="BUY"
    else: direction="NONE"
    if pressure_dir==direction and direction!="NONE" and not (
        (direction=="SELL" and (m15_down or m5_down)) or
        (direction=="BUY" and (m15_up or m5_up))):
        stage="EARLY_DIRECTIONAL_ROTATION"
    else:
        stage=("BREAKOUT_CONFIRMING" if m15_down or m15_up else
               "PRE_BREAKOUT_WATCH" if m5_down or m5_up else
               "EARLY_CLUSTER_ROTATION" if direction!="NONE" else "WAIT")
    breakout=round((low-m5current["c"])/pip(pair),2) if direction=="SELL" else (
             round((m5current["c"]-high)/pip(pair),2) if direction=="BUY" else None)
    breadth=cluster.get("jpy_strength_crosses",0)
    cluster_bonus=(breadth/4) if pair in JPY and direction=="SELL" else 0.0
    trend_evidence=int(m15[-1]["c"]<m15[-2]["c"]) if direction=="SELL" else (
                   int(m15[-1]["c"]>m15[-2]["c"]) if direction=="BUY" else 0)
    evidence_frac=(pressure.get("score",0)/4 if pressure_dir==direction and direction!="NONE" else 0)
    early_score=(1.0 if (m5_down or m5_up) else
                 1.0 if pressure_dir==direction and direction!="NONE" else
                 .7 if direction!="NONE" else 0)
    # 50% early detection and 50% independently observed directional
    # structure/momentum; higher TF alignment is not an early-watch veto.
    strength_score=min(1.0,.55*evidence_frac+.20*trend_evidence+
                       .15*cluster_bonus+.10*int(compression))
    score=round(.5*early_score+.5*strength_score,3)
    base.update(direction=direction,stage=stage,
                range_status="RANGING" if compression else "TRENDING_OR_TRANSITION",
                observed_reference_start_utc=reference[0]["open_utc"],
                observed_reference_end_utc=reference[-1]["close_utc"],
                observed_reference_duration_minutes=60,
                actual_range_start_utc=None,
                range_start_verification="UNAVAILABLE_4_BAR_REFERENCE_ONLY",
                range_high=high,range_low=low,range_width_pips=round(width,2),
                prior_comparable_width_pips=round(baseline,2) if baseline is not None else None,
                compression_observed=compression,
                latest_closed_m5_utc=m5current["close_utc"],
                latest_closed_m5=m5current["c"],
                latest_closed_m15_utc=m15[-1]["close_utc"],
                latest_closed_m15=m15[-1]["c"],
                distance_outside_range_pips=breakout,
                jpy_cluster_status=cluster.get("status") if pair in JPY else "NOT_JPY_CROSS",
                jpy_strength_cross_count=breadth if pair in JPY else None,
                early_opportunity_score_50pct=round(early_score,2),
                trend_strength_score_50pct=round(strength_score,2),
                research_rank_score=score,
                pressure_evidence=pressure,
                fresh_trigger=direction!="NONE",
                direction_invalidation_reference=pressure.get("invalidation_reference")
                    if direction==pressure_dir else (high if direction=="SELL" else low),
                reversal_watch_no_break_required=stage=="EARLY_DIRECTIONAL_ROTATION",
                watch_only=direction!="NONE",
                reason=("CLOSED_M15_RANGE_BREAK" if stage=="BREAKOUT_CONFIRMING" else
                        "CLOSED_M5_RANGE_BREAK_EARLY_WATCH_ONLY" if stage=="PRE_BREAKOUT_WATCH" else
                        "STRUCTURE_ROTATION_WITHOUT_BREAKOUT" if stage=="EARLY_DIRECTIONAL_ROTATION" else
                        "JPY_CLUSTER_AND_RANGE_BOUNDARY_PRESSURE" if stage=="EARLY_CLUSTER_ROTATION" else
                        "NO_CURRENT_EARLY_TRIGGER"))
    return base

def run(vol,calendar=None,at=None,previous=None,strict_freshness=True):
    at=at or datetime.now(UTC)
    quiet=is_quiet(at)
    offset=server_offset(vol or {}) if vol else None
    collected=parse((vol or {}).get("collected_at_utc"))
    source_age=(at-collected).total_seconds()/60 if collected else None
    input_valid=offset is not None and (not strict_freshness or
        (source_age is not None and -2<=source_age<=15))
    result={"generated_at_utc":at.isoformat(),"quiet_hours":quiet,
            "execution_allowed":False,"feed_valid":input_valid,
            "source_age_minutes":round(source_age,1) if source_age is not None else None,
            "server_offset_hours":offset/3600 if offset is not None else None,
            "purpose":"EARLY_DIRECTIONAL_WATCH_ONLY_NEVER_AN_EXECUTABLE_ORDER",
            "no_lookahead":"Only OHLC candles CLOSED before evaluation time are included",
            "pairs":[],"jpy_cluster":None,"top_five_early_priority":[],
            "active_episodes":[]}
    if not input_valid:
        result["status"]="MISSING_OR_STALE_SOURCE"
        result["pairs"]=[{"pair":p,"direction":"UNAVAILABLE","stage":"PARTIAL",
                           "reason":"INVALID_OR_STALE_SOURCE"} for p in PAIRS]
        return result
    cluster=currency_cluster(vol,at,offset)
    result["jpy_cluster"]=cluster
    rows=[detect_pair(p,vol,at,offset,cluster,calendar) for p in PAIRS]
    # Preserve a new reversal watch across a short counterbounce, unless the
    # original structural invalidation is hit or opposite pressure dominates.
    old_episodes={x.get("pair"):x for x in (previous or {}).get("active_episodes",[])
                  if isinstance(x,dict)}
    for row in rows:
        prev=old_episodes.get(row["pair"])
        if row.get("direction")!="NONE" or not prev or quiet:
            continue
        recent=parse(prev.get("last_observed_at_utc"))
        started=parse(prev.get("first_observed_at_utc"))
        if not recent or not started or not (0<=(at-recent).total_seconds()<=900):
            continue
        if not (0<=(at-started).total_seconds()<=5400):
            continue
        pd=prev.get("direction")
        inv=prev.get("invalidation_reference")
        price=row.get("latest_closed_m5")
        if pd not in ("SELL","BUY") or inv is None or price is None:
            continue
        invalid=(pd=="SELL" and price>=inv) or (pd=="BUY" and price<=inv)
        pressure=row.get("pressure_evidence",{})
        if invalid or (pressure.get("direction") not in ("NONE",pd)):
            continue
        row.update(direction=pd,stage="EARLY_ROTATION_TRACKING",
                   reason="EARLY_ROTATION_STILL_VALID_WITHOUT_NEW_TRIGGER",
                   watch_only=True,fresh_trigger=False,
                   direction_invalidation_reference=inv,
                   reversal_watch_no_break_required=True,
                   research_rank_score=round(max(.52,float(prev.get("research_rank_score",0))-.075),3))
    if quiet:
        for x in rows:x["stage"]="QUIET_HOURS";x["watch_only"]=False
    result["pairs"]=rows
    episodes=[]
    for row in rows:
        pair=row["pair"]
        prev=old_episodes.get(pair)
        triggered=row.get("direction") in ("BUY","SELL") and row.get("watch_only")
        if triggered:
            if prev and prev.get("direction")==row["direction"] and parse(prev.get("first_observed_at_utc")):
                age=(at-parse(prev["first_observed_at_utc"])).total_seconds()/60
                if 0<=age<=360:
                    first=prev["first_observed_at_utc"]
                    initial=prev.get("initial_closed_price")
                else:
                    first=at.isoformat();initial=row.get("latest_closed_m5")
            else:
                first=at.isoformat();initial=row.get("latest_closed_m5")
        elif prev and not quiet and parse(prev.get("last_observed_at_utc")):
            age=(at-parse(prev["last_observed_at_utc"])).total_seconds()/60
            if 0<=age<=360:
                episodes.append(dict(prev,current_condition="NO_NEW_TRIGGER_TRACKING_ONLY",
                                     execution_allowed=False))
            continue
        else:continue
        progress=(round((initial-row["latest_closed_m5"])/pip(pair),2)
                  if initial is not None and row["direction"]=="SELL" else
                  round((row["latest_closed_m5"]-initial)/pip(pair),2)
                  if initial is not None else None)
        episodes.append({"pair":pair,"direction":row["direction"],
                         "first_observed_at_utc":first,
                         "last_observed_at_utc":at.isoformat(),
                         "initial_closed_price":initial,
                         "latest_closed_price":row.get("latest_closed_m5"),
                         "stage":row.get("stage"),
                         "first_observed_to_now_pips":progress,
                         "research_rank_score":row.get("research_rank_score",0),
                         "invalidation_reference":row.get("direction_invalidation_reference") if first==at.isoformat()
                             else (prev.get("invalidation_reference") if prev else row.get("direction_invalidation_reference")),
                         "fresh_trigger":row.get("fresh_trigger",False),
                         "execution_allowed":False})
    result["active_episodes"]=episodes
    ranked=sorted([x for x in rows if x.get("watch_only")],key=lambda x:x["research_rank_score"],reverse=True)
    result["top_five_early_priority"]=[
        {"rank":i+1,"pair":x["pair"],"direction":x["direction"],
         "stage":x["stage"],"research_score":x["research_rank_score"],
         "jpy_cluster_status":x["jpy_cluster_status"],
         "range_low":x["range_low"],"range_high":x["range_high"],
         "invalidation_reference":x.get("direction_invalidation_reference"),
         "no_breakout_required":x.get("reversal_watch_no_break_required",False),
         "pressure_evidence":x.get("pressure_evidence",{}).get("evidence",[]),
         "entry_readiness":"TECHNICAL_WATCH_ONLY_MACRO_SPREAD_UNVERIFIED",
         "event_within_120_min":x["event_within_120_min"],
         "execution_allowed":False} for i,x in enumerate(ranked[:5])]
    result["status"]="RESEARCH_ONLY_QUIET" if quiet else "RESEARCH_ONLY_PARTIAL_MACRO"
    return result

def main():
    vol=load("fx_volatility.json")
    calendar=load("fx_economic_calendar.json")
    previous=load("fx_early_rotation.json")
    result=run(vol,calendar,previous=previous)
    Path("fx_early_rotation.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    dash=load("fx_scan_dashboard.json")
    if isinstance(dash,dict):
        dash["early_rotation_generated_at_utc"]=result["generated_at_utc"]
        dash["early_rotation_status"]=result.get("status")
        dash["early_rotation_jpy_cluster"]=result.get("jpy_cluster")
        dash["early_rotation_top_five"]=result["top_five_early_priority"]

        # Expose one canonical scanner direction while preserving the raw
        # lagging detector reading for accountability and audit.
        early_by_pair={x["pair"]:x for x in result.get("pairs",[])}
        for pairrow in dash.get("pairs",[]):
            early=early_by_pair.get(pairrow["pair"])
            pairrow["legacy_direction_before_early_override"]=pairrow.get("direction")
            pairrow["legacy_stage_before_early_override"]=pairrow.get("stage")
            pairrow["early_pressure_evidence"]=early.get("pressure_evidence") if early else None
            if not early or not early.get("watch_only"):
                pairrow["canonical_direction"]=pairrow.get("direction")
                continue
            pairrow["canonical_direction"]=early["direction"]
            pairrow["canonical_stage"]=early["stage"]
            pairrow["early_direction_conflicts_with_legacy"]=(
                pairrow.get("direction") in ("BUY","SELL") and
                pairrow["direction"]!=early["direction"])
            pairrow["directional_early_warning"]=early["direction"]
            pairrow["early_direction_invalidation_reference"]=early.get(
                "direction_invalidation_reference")
            pairrow["early_reversal_watch_no_break_required"]=early.get(
                "reversal_watch_no_break_required",False)
            if pairrow.get("source_valid") is True:
                pairrow["direction"]=early["direction"]
                pairrow["directional_bias"]=early["direction"]
                pairrow["stage"]=early["stage"]
                pairrow["entry_readiness"]="EARLY_TECHNICAL_WATCH_ONLY"
                if early.get("reversal_watch_no_break_required"):
                    pairrow["conditional_level_reference_only"]=None
        # Main Top Five must not bury a timely M5/15m turn behind the old
        # higher-timeframe score. Retain the old Top Five for audit.
        legacy_top=dash.get("top_five_technical_candidates",[])
        dash["top_five_legacy_technical_only"]=legacy_top
        merged={}
        for old in dash.get("pairs",[]):
            if old.get("source_valid") is not True or old.get("direction") not in ("BUY","SELL"):
                continue
            if old.get("entry_readiness") not in ("TECHNICAL_WATCH_ONLY","EARLY_TECHNICAL_WATCH_ONLY"):
                continue
            stage=old.get("stage")
            stage_early={"EARLY":.85,"CONFIRMING":.7,"CONTINUATION":.55,"EXTENDED":.2}.get(stage,.3)
            strength=min(1,max(0,float(old.get("direction_score") or 0)/11))
            if old.get("trade_type")=="TREND_CONTINUATION": strength=min(1,strength+.12)
            score=round(.5*stage_early+.5*strength,3)
            merged[old["pair"]]={
                "pair":old["pair"],"direction":old["direction"],"stage":stage,
                "trade_type":old.get("trade_type"),"direction_score":old.get("direction_score"),
                "entry_readiness":"TECHNICAL_WATCH_ONLY",
                "rank_score":score,"source":"CLOSED_M15_30M_TREND_WATCH",
                "execution_allowed":False,"conditional_level_reference_only":old.get("conditional_level_reference_only")}
        for early in result.get("pairs",[]):
            if not early.get("watch_only") or early.get("direction") not in ("BUY","SELL"):
                continue
            old=merged.get(early["pair"])
            merged[early["pair"]]={
                "pair":early["pair"],"direction":early["direction"],"stage":early["stage"],
                "trade_type":"EARLY_ROTATION_OR_BREAKOUT_WATCH",
                "direction_score":round(11*early["trend_strength_score_50pct"],1),
                "entry_readiness":"EARLY_TECHNICAL_WATCH_ONLY",
                "rank_score":early["research_rank_score"],
                "source":"CLOSED_M5_15M_CLUSTER_WATCH",
                "overrides_prior_technical_direction":(
                    next((p.get("early_direction_conflicts_with_legacy",False)
                          for p in dash.get("pairs",[]) if p["pair"]==early["pair"]),False)),
                "jpy_cluster_status":early.get("jpy_cluster_status"),
                "event_within_120_min":early.get("event_within_120_min"),
                "execution_allowed":False,
                "early_pressure_evidence":early.get("pressure_evidence",{}).get("evidence",[]),
                "reversal_watch_no_break_required":early.get("reversal_watch_no_break_required",False),
                "invalidation_reference":early.get("direction_invalidation_reference"),
                "conditional_level_reference_only":None if early.get("reversal_watch_no_break_required") else (
                    early["range_low"] if early["direction"]=="SELL" else early["range_high"])}
        ranked_merged=sorted(merged.values(),key=lambda x:(-x["rank_score"],x["pair"]))
        dash["top_five_technical_candidates"]=[
            dict(x,rank=i+1) for i,x in enumerate(ranked_merged[:5])]
        dash["top_five_note"]="50pct early price-rotation opportunity + 50pct directional structure. Reversal watches require NO breakout. New closed M15/M30 directional pressure overrides lagging EMA/legacy BUY direction when observed. All watches NEVER executable orders; macro/spreads UNVERIFIED."
        dash["all_11_ranked_directional_watches"]=ranked_merged
        dash["main_board_rebuilt_from_early_utc"]=result["generated_at_utc"]

        dash["early_rotation_all_11"]=[
            {"pair":x["pair"],"direction":x.get("direction"),"stage":x.get("stage"),
             "research_rank_score":x.get("research_rank_score"),
             "observed_reference_start_utc":x.get("observed_reference_start_utc"),
             "actual_range_start_utc":x.get("actual_range_start_utc"),
             "range_high":x.get("range_high"),"range_low":x.get("range_low")}
            for x in result["pairs"]]
        dash["early_rotation_episodes"]=result["active_episodes"]
        dash["early_rotation_rule"]="AGGRESSIVE EARLY STRUCTURE ROTATION: 4-bar lower highs/lows, 15m/30m momentum, failed pushes, no breakout required. 5m watch only; 1H/4H context not vetoes; no execution approval."
        Path("fx_scan_dashboard.json").write_text(json.dumps(dash,indent=2)+"\n",encoding="utf-8")
    print("EARLY_ROTATION",result.get("status"),"JPY",result.get("jpy_cluster",{}).get("status") if result.get("jpy_cluster") else None,
          "TOP",[(x["pair"],x["direction"],x["stage"]) for x in result["top_five_early_priority"]])

if __name__=="__main__":
    main()
