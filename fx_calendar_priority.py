#!/usr/bin/env python3
"""Scheduled macro-event priority, 11-pair mapping and coverage gaps.

Forex Factory public weekly calendar is NOT complete FXStreet calendar coverage.
Never convert a screenshot's displayed clock to ET without timezone metadata.
News/headlines are never an automatic BUY/SELL and no orders/alerts are sent.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from fx_macro_collector import PAIRS
from fx_news_priority import parse_utc, completed_event_reaction
from fx_approved_public_sources import FX_BLUE, parse_fx_blue
from fx_macro_collector import get

UTC=timezone.utc
ET=ZoneInfo("America/New_York")
OUTPUT=Path("fx_calendar_priority.json")
POLICY_TERMS=("central bank","monetary policy","fomc","fed chair","federal reserve",
              "fed governor","fed member","fomc member","boe","boj","rba",
              "rbnz","ecb","boc","interest rate decision","rate statement",
              "meeting minutes","governor","board member","speaks","speech",
              "press conference","testimony","policy decision")
MAJOR_TERMS=("cpi","core ppi","ppi","unemployment","employment change",
             "payroll","retail sales","gdp","jobs","inflation","consumer price",
             "policy rate")


def affected(pair,currency):
    return currency in (pair[:3],pair[3:]) or currency=="CNY" and (
        "AUD" in pair or "NZD" in pair)


def urgency(title,impact):
    title=str(title or "").lower()
    if any(k in title for k in POLICY_TERMS):
        return "HIGH_POLICY_SPEECH_OR_DECISION"
    if str(impact).lower()=="high" or any(k in title for k in MAJOR_TERMS):
        return "HIGH_MACRO_RELEASE_REVIEW"
    if str(impact).lower()=="medium":
        return "MEDIUM_MACRO_REVIEW"
    return "CALENDAR_CONTEXT"


def make_radar(calendar,previous=None,volatility=None,now=None,fx_blue=None):
    now=now or datetime.now(UTC)
    previous=previous or {}
    volatility=volatility or {}
    fx_blue=fx_blue or {}
    collected=parse_utc(calendar.get("collected_at_utc"))
    age=(now-collected).total_seconds()/60 if collected else None
    valid=calendar.get("status")=="VERIFIED" and isinstance(calendar.get("events"),list)
    fresh=valid and age is not None and -2<=age<=150
    blue_collected=parse_utc(fx_blue.get("collected_at_utc"))
    blue_age=(now-blue_collected).total_seconds()/60 if blue_collected else None
    blue_valid=fx_blue.get("status")=="DATED_UTC_PUBLIC_EVENTS" and blue_age is not None and -2<=blue_age<=45
    old={ (e.get("event_at_utc"),e.get("currency"),e.get("title")):e.get("first_seen_at_utc")
          for e in previous.get("monitored_events",[])
          if parse_utc(e.get("first_seen_at_utc")) }
    enriched=[]
    # Merge independent dated public events; do NOT treat incomplete weekly FF as exhaustive.
    candidate_events=[]
    if fresh:
        candidate_events.extend(calendar["events"])
    if blue_valid:
        candidate_events.extend(fx_blue.get("events") or [])
    de_duped=set()
    if candidate_events:
        for e in candidate_events:
            at=parse_utc(e.get("event_at_utc"))
            currency=e.get("currency")
            if not at or not currency or not now-timedelta(hours=2)<=at<=now+timedelta(days=2):
                continue
            title=str(e.get("title") or "").strip()
            if not title:
                continue
            uniqueness=(at.isoformat(),currency,re.sub(r"[^a-z0-9]+","",title.lower()))
            if uniqueness in de_duped:
                continue
            de_duped.add(uniqueness)
            names=[p for p in PAIRS if affected(p,currency)]
            if not names:
                continue
            minutes=(at-now).total_seconds()/60
            priority=urgency(title,e.get("impact"))
            status=("PRE_EVENT_30_MIN" if 0<=minutes<=30 else
                    "PRE_EVENT_120_MIN" if 30<minutes<=120 else
                    "POST_EVENT_30_MIN" if -30<=minutes<0 else
                    "POST_EVENT_120_MIN" if -120<=minutes< -30 else
                    "UPCOMING_48H")
            key=(at.isoformat(),currency,title)
            first=old.get(key) or (blue_collected.isoformat() if e.get("source_name")=="FX Blue public calendar" and blue_collected else collected.isoformat() if collected else now.isoformat())
            item={"title":title,"currency":currency,"event_at_utc":at.isoformat(),
                  "event_at_et":at.astimezone(ET).isoformat(),
                  "first_seen_at_utc":first,
                  "minutes_until_event":round(minutes,1),
                  "urgency":priority,"event_window":status,
                  "publisher_impact":e.get("impact"),
                  "forecast":e.get("forecast") or None,
                  "previous":e.get("previous") or None,
                  "actual":None,"actual_not_verified_by_weekly_calendar":True,
                  "source_name":e.get("source_name") or calendar.get("source_name"),
                  "publisher_time_basis":e.get("time_basis") or "UTC_TIMESTAMP_IN_FF_WEEKLY_JSON",
                  "affected_pairs":names,"trade_direction":"NONE",
                  "no_assumed_release_reaction":True}
            if -120<=minutes<0 and priority.startswith("HIGH"):
                item["per_pair_closed_15m_event_reaction"]={
                    p:completed_event_reaction(volatility,p,at.isoformat(),first)
                    for p in names}
            enriched.append(item)
    enriched.sort(key=lambda x:(not x["urgency"].startswith("HIGH"),
                                abs(x["minutes_until_event"])))
    per_pair={}
    for p in PAIRS:
        ev=[v for v in enriched if p in v["affected_pairs"]]
        urgent=[v for v in ev if v["urgency"].startswith("HIGH")]
        per_pair[p]={"upcoming_or_recent_critical":urgent[:12],
                     "relevant_events":ev[:20],
                     "critical_within_two_hours":[x for x in urgent if abs(x["minutes_until_event"])<=120],
                     "research_status":"CRITICAL_EVENT_WINDOW" if any(abs(x["minutes_until_event"])<=120 for x in urgent)
                                       else "UPCOMING_EVENTS" if ev else "NO_VERIFIED_FRESH_CALENDAR_EVENTS",
                     "source_coverage_incomplete":True,
                     "directional_vote":"NONE",
                     "no_event_is_not_proof_of_no_policy_speech":True}
    return {"schema_version":1,"generated_at_utc":now.isoformat(),
            "calendar_source":"Forex Factory/Fair Economy public weekly JSON",
            "calendar_collected_at_utc":calendar.get("collected_at_utc"),
            "calendar_age_minutes":round(age,1) if age is not None else None,
            "calendar_status":("FRESH_FF_PLUS_FXBLUE" if fresh and blue_valid else
                               "FRESH_FXBLUE_ONLY" if blue_valid else
                               "FRESH_FF_WEEKLY_ONLY" if fresh else "STALE_OR_UNAVAILABLE"),
            "fx_blue_public_calendar_status":fx_blue.get("status","UNAVAILABLE"),
            "fx_blue_collected_at_utc":fx_blue.get("collected_at_utc"),
            "fx_blue_verified_utc_events":len(fx_blue.get("events") or []) if blue_valid else 0,
            "approved_calendar_sources":["Forex Factory/Fair Economy","FX Blue public calendar"],
            "publisher_timezone_in_output":"UTC_WITH_CONVERTED_AMERICA_NEW_YORK",
            "fxstreet_calendar_coverage":"UNAVAILABLE_OAUTH_REQUIRED_NOT_INGESTED",
            "known_gap":"FXStreet calendar remains unavailable; FF and FX Blue public sites are best-effort and not exhaustive",
            "do_not_infer_calendar_timezone_from_device_clock":True,
            "monitored_events":enriched[:100],
            "pairs":per_pair,
            "research_priority_is_not_the_publisher_impact":True,
            "no_extra_sources_no_keys":True,"no_orders_or_alerts":True,
            "no_directional_calendar_votes":True}


def main():
    def load(path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (ValueError,OSError):
            return {}
    blue=parse_fx_blue(get(FX_BLUE,10))
    report=make_radar(load("fx_economic_calendar.json"),load(OUTPUT),
                      load("fx_volatility.json"),fx_blue=blue)
    OUTPUT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["calendar_status"],
                      "events":len(report["monitored_events"]),
                      "critical_pairs":sum(bool(x["critical_within_two_hours"])
                                          for x in report["pairs"].values()),
                      "uncovered_calendar_source":report["fxstreet_calendar_coverage"],
                      "fx_blue_public_calendar_status":report["fx_blue_public_calendar_status"],
                      "fx_blue_public_events":report["fx_blue_verified_utc_events"],
                      "no_orders":True}))


if __name__=="__main__":main()
