#!/usr/bin/env python3
"""Audit-only FX source collector. Never emits trading signals."""
import argparse, concurrent.futures, datetime as dt, json, os, sqlite3, urllib.request, urllib.error
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
ET=ZoneInfo("America/New_York")
def utc_now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def fetch(src,timeout):
    started=utc_now()
    request=urllib.request.Request(src["url"],headers={"User-Agent":"FXSourceAudit/0.2 (research; contact repository maintainer)"})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            sample=response.read(65536)
            result={"status":"retrieved","http_status":response.status,"bytes_sampled":len(sample),"content_type":response.headers.get("Content-Type"),"error":None}
    except urllib.error.HTTPError as error:
        result={"status":"http_error","http_status":error.code,"bytes_sampled":0,"content_type":None,"error":str(error)}
    except Exception as error:
        result={"status":"access_error","http_status":None,"bytes_sampled":0,"content_type":None,"error":str(error)}
    return {**src,**result,"attempted_at_utc":started,"attempted_at_et":dt.datetime.fromisoformat(started).astimezone(ET).isoformat(),"source_observation_time":None,"data_verified":False}
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--registry",default=str(ROOT/"sources.json"))
    parser.add_argument("--output",default=os.getenv("FX_REPORT_PATH",str(ROOT/"latest_report.json")))
    parser.add_argument("--database",default=os.getenv("FX_DATABASE_PATH",str(ROOT/"audit.sqlite3")))
    parser.add_argument("--timeout",type=float,default=10)
    parser.add_argument("--concurrency",type=int,default=8)
    parser.add_argument("--max-runtime",type=float,default=180,help="Maximum seconds for the entire source audit")
    args=parser.parse_args()
    sources=json.loads(Path(args.registry).read_text())
    ids=[s["id"] for s in sources]
    if not sources or len(ids)!=len(set(ids)) or any(not s.get("url","").startswith("https://") for s in sources):
        raise SystemExit("Invalid source registry")
    run_id=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    # Global deadline: never wait indefinitely for slow DNS, TLS, or web hosts.
    # Each registered source receives a result, including sources still in flight.
    import time
    started_mono=time.monotonic()
    executor=concurrent.futures.ThreadPoolExecutor(max_workers=max(1,args.concurrency))
    futures={executor.submit(fetch,source,args.timeout):source for source in sources}
    results=[]
    try:
        done,pending=concurrent.futures.wait(futures,timeout=max(1,args.max_runtime))
        for future in done:
            try: results.append(future.result())
            except Exception as error:
                src=futures[future]
                results.append({**src,"status":"collector_error","error":str(error),"attempted_at_utc":utc_now(),"source_observation_time":None,"data_verified":False})
        for future in pending:
            src=futures[future]
            future.cancel()
            results.append({**src,"status":"deadline_exceeded","error":"Global audit deadline exceeded; retrieval not confirmed","attempted_at_utc":utc_now(),"source_observation_time":None,"data_verified":False})
    finally:
        executor.shutdown(wait=False,cancel_futures=True)
    observed={r["id"] for r in results}
    missing=sorted(set(ids)-observed)
    report={"run_id":run_id,"finished_at_utc":utc_now(),"registry_count":len(ids),"attempted_count":len(observed),"source_attempt_coverage_pass":not missing and len(observed)==len(ids),"missing_source_ids":missing,"retrieved_count":sum(r["status"]=="retrieved" for r in results),"deadline_exceeded_count":sum(r["status"]=="deadline_exceeded" for r in results),"verified_live_data_count":0,"trading_evidence_gate_pass":False,"analysis_allowed":False,"reason":"Audit only: source responses are not parsed or verified; trading signals blocked","sources":sorted(results,key=lambda x:ids.index(x["id"]))}
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2))
    if args.database:
        db=Path(args.database);db.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(db) as con:
            con.execute("CREATE TABLE IF NOT EXISTS attempts (run_id TEXT, source_id TEXT, attempted_at_utc TEXT, status TEXT, http_status INTEGER, error TEXT, PRIMARY KEY(run_id,source_id))")
            con.executemany("INSERT OR REPLACE INTO attempts VALUES (?,?,?,?,?,?)",[(run_id,r["id"],r["attempted_at_utc"],r["status"],r.get("http_status"),r.get("error")) for r in results])
    print(json.dumps({k:v for k,v in report.items() if k!="sources"},indent=2))
    print("Report:",output)
if __name__=="__main__":main()
