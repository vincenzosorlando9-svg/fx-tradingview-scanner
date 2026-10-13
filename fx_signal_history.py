"""Persist first observed FX directional alerts across scheduled scanner runs.
Observation timestamps are scan times, NOT reconstructed first market moves.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

STATE=Path("fx_signal_history.json")
DASH=Path("fx_scan_dashboard.json")
PIP=lambda pair: .01 if pair.endswith("JPY") else .0001

def main():
    dash=json.loads(DASH.read_text())
    now=datetime.fromisoformat(dash["generated_at_utc"].replace("Z","+00:00"))
    if STATE.exists():
        state=json.loads(STATE.read_text())
    else:
        state={"version":1,"pairs":{},"initialized_at_utc":now.isoformat()}
    state.setdefault("pairs",{})
    for row in dash.get("pairs",[]):
        pair=row["pair"]
        item=state["pairs"].setdefault(pair,{"active":None,"history":[]})
        direction=row.get("direction")
        stage=row.get("stage")
        valid=row.get("source_valid") is True
        # The dashboard does not yet expose a live quote; use only a time-stamped
        # closed 15m candle close if present in the detector's underlying feed.
        # No invented entry price or pip performance.
        if not valid:
            if item["active"]:
                item["active"]["last_observation_status"]="DATA_UNAVAILABLE"
            continue
        if direction not in ("BUY","SELL"):
            if item["active"]:
                item["active"]["ended_at_utc"]=now.isoformat()
                item["active"]["end_reason"]="DIRECTION_NO_LONGER_DETECTED"
                item["history"].append(item["active"])
                item["history"]=item["history"][-100:]
                item["active"]=None
            continue
        price=row.get("last_closed_15m_price")
        price=float(price) if price is not None else None
        active=item["active"]
        if active and active["direction"]!=direction:
            active["ended_at_utc"]=now.isoformat()
            active["end_reason"]="DIRECTION_REVERSED"
            item["history"].append(active)
            item["history"]=item["history"][-100:]
            active=None
        if active is None:
            active={"direction":direction,"first_observed_at_utc":now.isoformat(),
                    "first_observed_stage":stage,"first_observed_source_valid":True,
                    "first_observed_move_maturity":row.get("move_maturity"),
                    "first_observed_origin_proxy":row.get("move_origin_proxy"),
                    "first_observed_closed_15m_price":price,
                    "observation_count":0,"last_observation_status":"ACTIVE"}
            item["active"]=active
        active["last_observed_at_utc"]=now.isoformat()
        active["last_observed_closed_15m_price"]=price
        first_price=active.get("first_observed_closed_15m_price")
        if price is not None and first_price is not None:
            sign=1 if direction=="BUY" else -1
            performance=round((price-first_price)*sign/PIP(pair),1)
            active["pips_since_first_observation"]=performance
            active["max_favorable_observed_pips"]=max(performance,active.get("max_favorable_observed_pips",0))
            active["max_adverse_observed_pips"]=min(performance,active.get("max_adverse_observed_pips",0))
        active["last_observed_stage"]=stage
        active["last_observed_move_maturity"]=row.get("move_maturity")
        active["last_observation_status"]="ACTIVE"
        active["observation_count"]+=1
        active["elapsed_since_first_observed_minutes"]=round((now-datetime.fromisoformat(active["first_observed_at_utc"])).total_seconds()/60,1)
        row["signal_history"]={
            "first_observed_at_utc":active["first_observed_at_utc"],
            "first_observed_stage":active["first_observed_stage"],
            "elapsed_since_first_observed_minutes":active["elapsed_since_first_observed_minutes"],
            "observation_count":active["observation_count"],
            "first_observed_closed_15m_price":first_price,
            "pips_since_first_observation":active.get("pips_since_first_observation"),
            "max_favorable_observed_pips":active.get("max_favorable_observed_pips"),
            "max_adverse_observed_pips":active.get("max_adverse_observed_pips"),
            "first_observed_move_maturity":active["first_observed_move_maturity"],
            "note":"First recorded scanner observation, not actual market move origin; historical first alerts unavailable before tracker initialization"}
    # Display EVERY active first-observed episode, even when latest detector
    # says EXTENDED or a provider-price discrepancy blocks execution.
    # Historical visibility never overrides readiness/safety.
    episode_board=[]
    for row in dash.get("pairs",[]):
        item=state["pairs"].get(row["pair"],{})
        active=item.get("active")
        if not active or active.get("direction") not in ("BUY","SELL"):
            continue
        first=active.get("first_observed_at_utc")
        try:
            age=(now-datetime.fromisoformat(first.replace("Z","+00:00"))).total_seconds()/60
        except (ValueError,TypeError,AttributeError):
            continue
        # Limit current board to actionable recent observations; history remains persisted.
        if age<0 or age>360:
            continue
        ready=row.get("entry_readiness")
        raw=row.get("stage")
        active_direction=active["direction"]
        travelled=active.get("pips_since_first_observation")
        score=row.get("direction_score")
        score=max(0,min(float(score or 0),11))
        # 50% opportunity freshness and 50% directional strength.
        stage_score={"EARLY":1,"CONFIRMING":.85,"CONTINUATION":.6,"EXTENDED":.15}.get(raw,.3)
        maturity_penalty=.30 if isinstance(travelled,(int,float)) and travelled>=20 else 0
        opportunity=max(0,stage_score-maturity_penalty)
        rank_score=round(.5*opportunity+.5*score/11,3)
        episode_board.append({
            "pair":row["pair"],
            "direction":active_direction,
            "stage":raw,
            "first_observed_at_utc":first,
            "first_observed_stage":active.get("first_observed_stage"),
            "first_observed_closed_15m_price":active.get("first_observed_closed_15m_price"),
            "last_observed_at_utc":active.get("last_observed_at_utc"),
            "last_observed_closed_15m_price":active.get("last_observed_closed_15m_price"),
            "pips_since_first_observation":travelled,
            "elapsed_minutes":round(age,1),
            "technical_readiness":ready,
            "detector_reasons":row.get("detector_reasons",[]),
            "price_feed_divergence_pips":row.get("technical_price_divergence_pips"),
            "visibility_status":"TRACKED_BUT_NOT_EXECUTABLE" if ready!="TECHNICAL_WATCH_ONLY" else "RESEARCH_WATCH",
            "execution_allowed":False,
            "ranking_score_research_only":rank_score,
        })
    episode_board.sort(key=lambda x:(-x["ranking_score_research_only"],x["pair"]))
    dash["active_episode_board"]=episode_board
    dash["active_episode_count"]=len(episode_board)
    dash["active_episode_method"]="Preserve timestamp of first recorded direction regardless of EXTENDED/data-divergence; do not infer actual beginning of market move."
    dash["episode_omitted_from_top_five"]=[
        {"pair":e["pair"],"direction":e["direction"],
         "first_observed_at_utc":e["first_observed_at_utc"],
         "stage":e["stage"],"visibility_status":e["visibility_status"]}
        for e in episode_board
        if e["pair"] not in {x["pair"] for x in dash.get("top_five_technical_candidates",[])}
    ]
    state["last_updated_at_utc"]=now.isoformat()
    dash["signal_history_initialized_at_utc"]=state["initialized_at_utc"]
    dash["signal_history_method"]="Persist first observed valid directional scan, maintain across runs; never reset on unchanged direction"
    STATE.write_text(json.dumps(state,indent=2)+"\n")
    DASH.write_text(json.dumps(dash,indent=2)+"\n")
    print("Tracked",sum(1 for r in dash["pairs"] if r.get("signal_history")),"active observed directions")

if __name__=="__main__":
    main()
