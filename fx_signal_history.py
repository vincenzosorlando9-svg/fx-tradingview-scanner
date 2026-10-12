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
    state["last_updated_at_utc"]=now.isoformat()
    dash["signal_history_initialized_at_utc"]=state["initialized_at_utc"]
    dash["signal_history_method"]="Persist first observed valid directional scan, maintain across runs; never reset on unchanged direction"
    STATE.write_text(json.dumps(state,indent=2)+"\n")
    DASH.write_text(json.dumps(dash,indent=2)+"\n")
    print("Tracked",sum(1 for r in dash["pairs"] if r.get("signal_history")),"active observed directions")

if __name__=="__main__":
    main()
