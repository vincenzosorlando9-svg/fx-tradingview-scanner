#!/usr/bin/env python3
"""Zero-cost GitHub Actions 4-slot FX scanner with fallback attempts.

Primary :02/:17/:32/:47, backup :05/:20/:35/:50 UTC. The *expected closed-bar time* is
the authority, not the GitHub workflow creation time or provider fetch time.
No broker order, paid source, API key or external scheduler.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_exact_candle_gate import expected_slot, market_open, validate
from fx_early_rotation import parse

UTC=timezone.utc
GATE=Path("fx_scan_gate.json")
HEALTH=Path("fx_scan_health.json")
HISTORY=Path("fx_scan_slot_history.json")
RETRY_INTERVAL_SECONDS=10
START_TOLERANCE_SECONDS=480
# Backups can start at :05/:20/:35/:50, or arrive late. No new
# signal is publishable after the deadline. Hard cutoff remains < next close.
# The exact slot should be available early; never chase a 15m-old candle.
LATEST_ACCEPTABLE_COMPLETION_SECONDS=570
HISTORY_CAP=384
EXPECTED_PAIRS=11


def now_utc():
    return datetime.now(UTC)


def load(path):
    try:
        value=json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}


def save(path,object_):
    Path(path).write_text(json.dumps(object_,indent=2,ensure_ascii=False)+"\n",
                          encoding="utf-8")


def job_output(key,value):
    out=os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out,"a",encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def slot_open(slot):
    when=parse(slot.get("candle_slot_close_utc"))
    return bool(when and market_open(when-timedelta(seconds=1)))


def verified_existing_slot(slot, history=None, unified=None):
    """Do NOT duplicate a previously published EXACT-CANDLE success.

    Only a scheduled successful signal for the very same :02/:17/:32/:47
    logical slot counts. Do not trust GitHub file mtime or push preflights.
    """
    history=history if history is not None else load(HISTORY)
    unified=unified if unified is not None else load("fx_unified_signals.json")
    expected=slot["candle_slot_close_utc"]
    published_rows=unified.get("all_11") or []
    if len(published_rows)!=EXPECTED_PAIRS or any(
        (r.get("reference_prices") or {}).get("closed_at_utc")!=expected
        for r in published_rows
    ):
        return False
    for prior in reversed(history.get("slots") or []):
        if prior.get("scheduled_for_utc")!=slot["scheduled_for_utc"]:
            continue
        return (
            prior.get("status")=="FULL_REPORT_EXACT_CANDLES_VERIFIED"
            and prior.get("signal_publication_allowed") is True
            and (prior.get("is_scheduled_trigger") is True or
                 prior.get("trigger_event")=="schedule")
            and prior.get("expected_candle_close_utc")==expected
            and prior.get("validated_pairs")==EXPECTED_PAIRS
            and (prior.get("expected_closes") or {}).get("M15")==expected
            and prior.get("unified_generated_at_utc")==unified.get("generated_at_utc")
        )
    return False


def collect():
    start=now_utc()
    slot=expected_slot(start)
    current={"schema_version":1,"scheduled_for_utc":slot["scheduled_for_utc"],
             "expected_candle_close_utc":slot["candle_slot_close_utc"],
             "started_at_utc":start.isoformat(),
             "status":"INIT","attempts":0,"observations":[],
             "expected_closes":{},"observed_closes":{},
             "validated_pairs":0,"signal_publication_allowed":False,
             "no_trades":True,"timing_basis":"EXACT_UTC_15M_SLOT",
             "trigger_event":os.getenv("GITHUB_EVENT_NAME","UNKNOWN"),
             "is_scheduled_trigger":os.getenv("GITHUB_EVENT_NAME")=="schedule",
             "scan_trigger_type":"backup" if os.getenv("FX_SCAN_CRON","").startswith("5,20,35,50 ") else "primary_or_manual",
             "actual_start_delay_seconds":slot["seconds_after_target"]}
    job_output("ready","false")
    if verified_existing_slot(slot):
        # Applies to backups AND delayed primary jobs: never overwrite a
        # previously completed exact-candle slot or emit duplicate signals.
        current["status"]="SKIP_ALREADY_VERIFIED"
        current["prior_success_reused"]=True
        save(GATE,current)
        print("BACKUP_SKIPPED_PRIOR_VALIDATED_SLOT",slot["scheduled_for_utc"])
        return 0
    if not slot_open(slot):
        current["status"]="MARKET_CLOSED"
        save(GATE,current)
        print("EXACT_SLOT",current["status"],current["scheduled_for_utc"])
        return 0
    if not slot["accepting_new_scan"]:
        current["status"]="MISSED_SCHEDULED_START_TOO_LATE"
        save(GATE,current)
        print("EXACT_SLOT",current["status"],slot["seconds_after_target"])
        return 1
    due=parse(slot["scheduled_for_utc"])
    deadline=due+timedelta(seconds=START_TOLERANCE_SECONDS)
    while True:
        current["attempts"]+=1
        try:
            subprocess.run([sys.executable,"forextoolkits_collector.py"],
                           check=True,timeout=35)
            source=load("fx_volatility.json")
            result=validate(source,now_utc(),slot_close=slot["candle_slot_close_utc"])
        except Exception as exc:
            result={"status":"COLLECTOR_ERROR","missing":[type(exc).__name__]}
        current["observations"].append(
            {"checked_at_utc":now_utc().isoformat(),"status":result["status"],
             "first_missing":(result.get("missing") or [])[:12]})
        if result.get("signal_publication_allowed"):
            current["status"]="EXACT_CANDLES_VERIFIED"
            current["validated_pairs"]=result["validated_pairs"]
            current["expected_closes"]=result["expected_closes"]
            current["observed_closes"]=result["observed_closes"]
            current["source_collected_at_utc"]=result["source_collected_at_utc"]
            current["server_offset_seconds"]=result["source_clock_correction_seconds"]
            save(GATE,current)
            job_output("ready","true")
            print("EXACT_SLOT_VERIFIED",current["scheduled_for_utc"],
                  current["expected_closes"],"attempts",current["attempts"])
            return 0
        remaining=(deadline-now_utc()).total_seconds()
        if remaining<RETRY_INTERVAL_SECONDS:
            current["status"]="REQUIRED_CANDLE_MISSING_DEADLINE"
            current["missing"]=result.get("missing",[])[:80]
            save(GATE,current)
            print("EXACT_SLOT",current["status"],current["scheduled_for_utc"],
                  "attempts",current["attempts"])
            return 1
        time.sleep(RETRY_INTERVAL_SECONDS)


def finalize():
    gate=load(GATE)
    if gate.get("status")!="EXACT_CANDLES_VERIFIED":
        raise RuntimeError("CANDLE_GATE_NOT_VERIFIED")
    due=parse(gate["scheduled_for_utc"])
    if now_utc()>due+timedelta(seconds=LATEST_ACCEPTABLE_COMPLETION_SECONDS):
        raise RuntimeError("FULL_REPORT_FINISHED_TOO_LATE_FOR_THIS_SLOT")
    unified=load("fx_unified_signals.json")
    dash=load("fx_scan_dashboard.json")
    report=load("fx_scan_report.json")
    rows=unified.get("all_11") or []
    expected15=gate["expected_closes"]["M15"]
    assert len(rows)==EXPECTED_PAIRS and unified.get("pair_count")==EXPECTED_PAIRS
    assert dash.get("source_versions_match") is True
    assert unified.get("source_technical_generated_at_utc")==dash.get("generated_at_utc")
    assert all((r.get("reference_prices") or {}).get("closed_at_utc")==expected15
               and r.get("technical_15m30m_fresh") is True for r in rows)
    assert [r["pair"] for r in report["top_five_published_ranking"]["rows"]]==[
        r["pair"] for r in unified["top_five"]]
    assert len(report["fifteen_layer_macro_first_audit"])==15
    gate["status"]="FULL_REPORT_EXACT_CANDLES_VERIFIED"
    gate["signal_publication_allowed"]=True
    gate["full_report_verified_at_utc"]=now_utc().isoformat()
    gate["unified_generated_at_utc"]=unified["generated_at_utc"]
    save(GATE,gate)
    print("FULL_REPORT_EXACT_VALIDATED",gate["scheduled_for_utc"],
          "M15",expected15,"M30",gate["expected_closes"]["M30"],
          "H1",gate["expected_closes"]["H1"])


def missed_since(previous,requested_slot):
    """Missing *publication records*, never invented trading candles or alerts."""
    seen=[parse(row.get("scheduled_for_utc")) for row in previous]
    seen=[dt for dt in seen if dt and dt<requested_slot]
    if not seen:
        return []
    cursor=max(seen)+timedelta(minutes=15)
    gaps=[]
    while cursor<requested_slot and len(gaps)<HISTORY_CAP:
        if market_open(cursor-timedelta(minutes=2,seconds=1)):
            gaps.append({"scheduled_for_utc":cursor.isoformat(),
                         "status":"NO_SUCCESSFUL_OR_FAILED_SLOT_RECORD_FOUND",
                         "signal_publication_allowed":False,
                         "not_a_replayed_or_backfilled_signal":True})
        cursor+=timedelta(minutes=15)
    return gaps


def record():
    gate=load(GATE)
    if gate.get("status")=="SKIP_ALREADY_VERIFIED":
        # No fresh collection performed, so keep the original successful
        # publication health and signal history untouched.
        job_output("publish_signals","false")
        print("BACKUP_IDEMPOTENT_SKIP_NO_NEW_HEALTH_OR_SIGNALS",
              gate.get("scheduled_for_utc"))
        return
    if not gate:
        slot=expected_slot(now_utc())
        gate={"scheduled_for_utc":slot["scheduled_for_utc"],
              "expected_candle_close_utc":slot["candle_slot_close_utc"],
              "status":"GATE_NOT_STARTED","signal_publication_allowed":False,
              "started_at_utc":now_utc().isoformat()}
    ready=(gate.get("status")=="FULL_REPORT_EXACT_CANDLES_VERIFIED"
           and os.getenv("PIPELINE_OUTCOME")=="success")
    if not ready and gate.get("status") in ("EXACT_CANDLES_VERIFIED",
                                            "FULL_REPORT_EXACT_CANDLES_VERIFIED"):
        gate["status"]="FULL_PIPELINE_FAILED_NO_SIGNAL_PUBLICATION"
    gate["signal_publication_allowed"]=ready
    gate["trigger_event"]=os.getenv("GITHUB_EVENT_NAME","UNKNOWN")
    gate["is_scheduled_trigger"]=gate["trigger_event"]=="schedule"
    gate["recorded_at_utc"]=now_utc().isoformat()
    gate["commit_at_utc"]="NOT_YET_VERIFIED_AT_RECORD_TIME"
    prior=load(HISTORY).get("slots") or []
    previous=next((p for p in reversed(prior) if
                   p.get("scheduled_for_utc")==gate["scheduled_for_utc"]),None)
    if previous:
        gate["previous_attempts_for_slot"]=(previous.get("previous_attempts_for_slot") or [])+[
            {"started_at_utc":previous.get("started_at_utc"),
             "status":previous.get("status"),
             "trigger_event":previous.get("trigger_event"),
             "scan_trigger_type":previous.get("scan_trigger_type"),
             "missing":(previous.get("missing") or [])[:12]}
        ]
    at=parse(gate["scheduled_for_utc"])
    gaps=missed_since(prior,at)
    recent=[x for x in prior if x.get("scheduled_for_utc")!=gate["scheduled_for_utc"]]
    recent.extend(gaps+[gate])
    recent=sorted(recent,key=lambda x:x["scheduled_for_utc"])[-HISTORY_CAP:]
    save(HISTORY,{"generated_at_utc":now_utc().isoformat(),"slots":recent,
                  "gap_means_missing_publication_record_not_missing_market_history":True,
                  "historical_misses_are_not_backfilled_signals":True})
    save(HEALTH,{"generated_at_utc":now_utc().isoformat(),
                 "schedule_utc_minutes":[2,17,32,47],
                 "backup_schedule_utc_minutes":[5,20,35,50],
                 "source":"GITHUB_ACTIONS_NO_COST_DEFAULT_RUNNER",
                 "last_slot":gate,
                 "unrecorded_slots_discovered":len(gaps),
                 "last_successful_slot_utc":next(
                     (x["scheduled_for_utc"] for x in reversed(recent)
                      if x.get("signal_publication_allowed")),None),
                 "last_successful_scheduled_slot_utc":next(
                     (x["scheduled_for_utc"] for x in reversed(recent)
                      if x.get("signal_publication_allowed") and
                      x.get("is_scheduled_trigger")),None),
                 "publishes_only_with_exact_m15_m30_h1":True,
                 "signal_publication_allowed":ready,
                 "not_a_guaranteed_clock_or_broker_feed":True,
                 "trading_orders_placed":False})
    job_output("publish_signals","true" if ready else "false")
    print("SLOT_RECORD",gate["scheduled_for_utc"],gate["status"],
          "publish_signals",ready,"missed_slots_found",len(gaps))


def main():
    phase=sys.argv[1] if len(sys.argv)>1 else ""
    if phase=="collect":
        return collect()
    if phase=="finalize":
        finalize()
        return 0
    if phase=="record":
        record()
        return 0
    raise SystemExit("USAGE: fx_github_slot.py collect|finalize|record")


if __name__=="__main__":
    sys.exit(main())
