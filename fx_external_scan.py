#!/usr/bin/env python3
"""Four-slot Render cron publisher for closed M15/M30/H1 research scans.

Run on Render at 02,17,32,47 UTC. Fresh shallow-clone at each run preserves
historical signal episodes; no missing or old candles are accepted as new.
Required secret: GITHUB_WRITE_TOKEN (fine-grained Contents Read/Write only).
No trades or trading alerts. No paid services provisioned by this script.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_exact_candle_gate import expected_slot, market_open, validate

UTC=timezone.utc
REPO="https://github.com/vincenzosorlando9-svg/fx-tradingview-scanner.git"
GITHUB_REF="main"
SCAN_SCRIPTS=[
    "scanner.py", "rotation_detector.py","fx_daily_weekly_levels.py",
    "fx_dashboard.py","fx_early_rotation.py","fx_signal_history.py",
    "fx_news_priority.py","fx_calendar_priority.py",
    "fx_signal_fusion_refresh.py","fx_scan_report.py"
]
OUTPUT_FILES=[
    "fx_volatility.json","fx_technicals.json","fx_rotation_signals.json",
    "fx_scan_dashboard.json","fx_daily_weekly_levels.json",
    "fx_signal_history.json","fx_early_rotation.json",
    "fx_news_priority.json","fx_calendar_priority.json",
    "fx_unified_signals.json","fx_scan_report.json","fx_scan_report.md",
    "fx_scan_health.json","fx_scan_slot_history.json",
]
MAX_RETRY_AFTER_DUE_SECONDS=240
MAX_COMPLETE_AFTER_DUE_SECONDS=570
RETRY_INTERVAL_SECONDS=9


def utcnow():
    return datetime.now(UTC)


def sh(args,cwd=None,timeout=95,env=None):
    subprocess.run(args,cwd=cwd,env=env,timeout=timeout,check=True,
                   stdout=sys.stdout,stderr=sys.stderr)


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return {}


def put(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",
                          encoding="utf-8")


def latest_expected_slot_record(slot_time,prev):
    """Record a missing scheduled slot, without manufacturing candles or trades."""
    at=datetime.fromisoformat(slot_time)
    older=[
        datetime.fromisoformat(x["scheduled_for_utc"])
        for x in prev if x.get("scheduled_for_utc") and
        x["scheduled_for_utc"]<slot_time
    ]
    if not older:
        return []
    last=max(older)
    gaps=[]
    cursor=last+timedelta(minutes=15)
    while cursor<at and len(gaps)<288:
        if market_open(cursor-timedelta(minutes=2,seconds=1)):
            gaps.append({"scheduled_for_utc":cursor.isoformat(),
                         "status":"NO_RECORDED_PUBLICATION_AT_SCHEDULED_SLOT",
                         "exact_candle_verified":False,
                         "not_a_backfilled_signal":True})
        cursor+=timedelta(minutes=15)
    return gaps


def push(repo_path,message):
    token=os.environ.get("GITHUB_WRITE_TOKEN")
    if not token:
        raise RuntimeError("MISSING_GITHUB_WRITE_TOKEN_CANNOT_PUBLISH")
    env=os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="fxcred-") as path:
        askpass=Path(path)/"askpass.py"
        askpass.write_text(
            "#!/usr/bin/env python3\n"
            "import os,sys\n"
            "print(os.environ.get('GITHUB_WRITE_TOKEN','') "
            "if 'password' in ' '.join(sys.argv).lower() else 'x-access-token')\n",
            encoding="utf-8")
        askpass.chmod(0o700)
        env["GIT_ASKPASS"]=str(askpass)
        env["GIT_TERMINAL_PROMPT"]="0"
        sh(["git","config","user.name","fx-candle-scheduler"],cwd=repo_path,env=env)
        sh(["git","config","user.email","fx-scheduler@users.noreply.github.com"],cwd=repo_path,env=env)
        sh(["git","add","--"]+[p for p in OUTPUT_FILES if (Path(repo_path)/p).exists()],
           cwd=repo_path,env=env)
        changed=subprocess.run(["git","diff","--cached","--quiet"],cwd=repo_path)
        if changed.returncode==0:
            print("NOTHING_TO_PUBLISH")
            return "UNCHANGED"
        sh(["git","commit","-m",message],cwd=repo_path,env=env)
        for attempt in range(4):
            try:
                sh(["git","pull","--rebase","origin",GITHUB_REF],cwd=repo_path,env=env,timeout=30)
                sh(["git","push","origin","HEAD:"+GITHUB_REF],cwd=repo_path,env=env,timeout=40)
                return subprocess.check_output(["git","rev-parse","HEAD"],cwd=repo_path,text=True).strip()
            except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
                subprocess.run(["git","rebase","--abort"],cwd=repo_path,
                               env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                time.sleep(2)
        raise RuntimeError("GITHUB_PUBLICATION_FAILED_AFTER_FOUR_ATTEMPTS")


def analyze(repo_path,slot,now,skip_wait=False):
    close=datetime.fromisoformat(slot["candle_slot_close_utc"])
    due=datetime.fromisoformat(slot["scheduled_for_utc"])
    entry={"scheduled_for_utc":slot["scheduled_for_utc"],
           "expected_candle_slot_close_utc":close.isoformat(),
           "started_at_utc":now.isoformat(),"finished_at_utc":None,
           "status":"PENDING","source_checks":[],"attempts":0,
           "expected_closes":{},"observed_closes":{},
           "exact_candle_verified":False,"publication_requested":False,
           "no_trade_or_alert":True}
    if not market_open(close-timedelta(seconds=1)):
        entry["status"]="MARKET_CLOSED_NO_CANDLES_DUE"
        return entry
    if not slot["accepting_new_scan"]:
        entry["status"]="MISSED_SCHEDULER_START_TOO_LATE"
        return entry
    until=due+timedelta(seconds=MAX_RETRY_AFTER_DUE_SECONDS)
    gate=None
    while True:
        entry["attempts"]+=1
        try:
            sh([sys.executable,"forextoolkits_collector.py"],cwd=repo_path,timeout=35)
            vol=load(Path(repo_path)/"fx_volatility.json")
            gate=validate(vol,utcnow(),slot_close=close.isoformat())
        except Exception as exc:
            gate={"status":"SOURCE_FETCH_FAILED","missing":[type(exc).__name__]}
        entry["source_checks"].append({
            "checked_at_utc":utcnow().isoformat(),"status":gate["status"],
            "first_missing":(gate.get("missing") or [])[:5],
            "source_collected_at_utc":gate.get("source_collected_at_utc")})
        if gate.get("signal_publication_allowed"):
            break
        if skip_wait or utcnow()+timedelta(seconds=RETRY_INTERVAL_SECONDS)>until:
            entry["status"]="CANDLE_NOT_AVAILABLE_WITHIN_RETRY_WINDOW"
            entry["missing_candle_evidence"]=gate.get("missing",[])[:80]
            return entry
        time.sleep(RETRY_INTERVAL_SECONDS)
    entry["expected_closes"]=gate["expected_closes"]
    entry["observed_closes"]=gate["observed_closes"]
    entry["exact_candle_verified"]=True
    for script in SCAN_SCRIPTS:
        if utcnow()>due+timedelta(seconds=MAX_COMPLETE_AFTER_DUE_SECONDS):
            entry["status"]="SCAN_TOO_LATE_FOR_THIS_15M_SLOT"
            entry["exact_candle_verified"]=False
            return entry
        try:
            sh([sys.executable,script],cwd=repo_path,timeout=85)
        except Exception as exc:
            entry["status"]="PIPELINE_STEP_FAILED"
            entry["failed_script"]=script
            entry["failure_type"]=type(exc).__name__
            entry["exact_candle_verified"]=False
            return entry
    unified=load(Path(repo_path)/"fx_unified_signals.json")
    dash=load(Path(repo_path)/"fx_scan_dashboard.json")
    expected15=gate["expected_closes"]["M15"]
    valid=(unified.get("pair_count")==11 and
           len(unified.get("all_11") or [])==11 and
           dash.get("source_versions_match") is True and
           unified.get("source_technical_generated_at_utc")==dash.get("generated_at_utc") and
           all((x.get("reference_prices") or {}).get("closed_at_utc")==expected15 and
               x.get("technical_15m30m_fresh") is True
               for x in unified["all_11"]))
    if not valid:
        entry["status"]="FINAL_SIGNAL_VERSION_OR_CANDLE_MISMATCH"
        entry["exact_candle_verified"]=False
        return entry
    if utcnow()>due+timedelta(seconds=MAX_COMPLETE_AFTER_DUE_SECONDS):
        entry["status"]="FINISHED_TOO_LATE_NO_CURRENT_PUBLISH"
        entry["exact_candle_verified"]=False
        return entry
    entry["status"]="PASS_FRESH_CANDLE_SIGNAL_PREPARED_FOR_GIT_PUBLICATION"
    entry["publication_requested"]=True
    entry["unified_signal_generated_at_utc"]=unified["generated_at_utc"]
    entry["completed_at_utc"]=utcnow().isoformat()
    return entry


def main():
    now=utcnow()
    slot=expected_slot(now)
    with tempfile.TemporaryDirectory(prefix="fx-slot-") as root:
        working=Path(root)/"repo"
        # Fresh shallow checkout: prior GitHub state and recorded episodes are preserved.
        sh(["git","clone","--quiet","--depth","1","--branch",GITHUB_REF,REPO,str(working)],
           timeout=55)
        os.chdir(working)
        entry=analyze(working,slot,now,skip_wait=os.getenv("FX_SCAN_SINGLE_ATTEMPT")=="1")
        history=load("fx_scan_slot_history.json")
        previous=history.get("slots") or []
        gaps=latest_expected_slot_record(entry["scheduled_for_utc"],previous)
        for skipped in gaps:
            print("UNRECORDED_SLOT",skipped["scheduled_for_utc"])
        entry["finished_at_utc"]=utcnow().isoformat()
        new_history=[s for s in previous
                     if s.get("scheduled_for_utc")!=entry["scheduled_for_utc"]]
        new_history.extend(gaps+[entry])
        new_history.sort(key=lambda v:v["scheduled_for_utc"])
        put("fx_scan_slot_history.json",{
            "updated_at_utc":utcnow().isoformat(),"slots":new_history[-288:],
            "retained_slot_limit":288,
            "unrecorded_gap_is_not_price_history_gap":True,
            "no_hindsight_backfill_claims":True})
        put("fx_scan_health.json",{
            "generated_at_utc":utcnow().isoformat(),
            "last_slot":entry,
            "history_source":"fx_scan_slot_history.json",
            "schedule_utc":":02 :17 :32 :47",
            "github_publication_completed_at_utc":"VERIFY_BY_GITHUB_COMMIT_AFTER_PUSH",
            "no_trades":True,"candle_gap_blocked_publication":not entry["publication_requested"]})
        try:
            commit=push(working,"Record exact FX candle slot "+
                        entry["scheduled_for_utc"]+" "+entry["status"])
        except Exception as exc:
            print("CRITICAL_GITHUB_PUBLICATION_FAILED",type(exc).__name__,str(exc))
            raise
        print(json.dumps({"status":entry["status"],
                          "slot":entry["scheduled_for_utc"],
                          "expected_closed":entry["expected_candle_slot_close_utc"],
                          "attempts":entry["attempts"],
                          "git_commit":commit,
                          "signal_published":entry["publication_requested"]}))
        if entry["status"] not in (
            "PASS_FRESH_CANDLE_SIGNAL_PREPARED_FOR_GIT_PUBLICATION",
            "MARKET_CLOSED_NO_CANDLES_DUE"):
            return 2
    return 0

if __name__=="__main__":
    sys.exit(main())
