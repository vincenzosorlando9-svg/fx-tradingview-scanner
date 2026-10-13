"""Regression tests for central-bank schedule priority and timezone integrity."""
import unittest
from datetime import datetime,timezone,timedelta
from fx_calendar_priority import make_radar,urgency,affected
NOW=datetime(2026,10,13,8,20,tzinfo=timezone.utc)
def event(title="BoJ Governor Ueda Speech",currency="JPY",at="2026-10-13T08:30:00+00:00",impact="Low"):
    return {"title":title,"currency":currency,"event_at_utc":at,
            "impact":impact,"forecast":"","previous":""}
def feed(events):
    return {"status":"VERIFIED","collected_at_utc":"2026-10-13T08:19:00+00:00",
            "source_name":"Forex Factory / Fair Economy weekly calendar",
            "events":events}

class CalendarPriorityTests(unittest.TestCase):
    def test_boJ_speech_prioritized_before_broker_direction(self):
        report=make_radar(feed([event()]),now=NOW)
        row=report["pairs"]["AUDJPY"]
        self.assertEqual(row["research_status"],"CRITICAL_EVENT_WINDOW")
        self.assertEqual(row["upcoming_or_recent_critical"][0]["event_window"],"PRE_EVENT_30_MIN")
        self.assertEqual(row["upcoming_or_recent_critical"][0]["urgency"],"HIGH_POLICY_SPEECH_OR_DECISION")
        self.assertEqual(row["upcoming_or_recent_critical"][0]["event_at_et"],"2026-10-13T04:30:00-04:00")
        self.assertEqual(row["upcoming_or_recent_critical"][0]["trade_direction"],"NONE")
        self.assertEqual(report["fxstreet_calendar_coverage"],"UNAVAILABLE_OAUTH_REQUIRED_NOT_INGESTED")
        self.assertTrue(report["no_orders_or_alerts"])
        self.assertEqual(len(report["pairs"]),11)

    def test_speech_missing_from_ff_not_fabricated(self):
        f=feed([event("US retail sales","USD")])
        radar=make_radar(f,now=NOW)
        self.assertFalse(any("Ueda" in e["title"] for e in radar["monitored_events"]))
        self.assertTrue(radar["pairs"]["AUDJPY"]["source_coverage_incomplete"])
        self.assertTrue(radar["pairs"]["AUDJPY"]["no_event_is_not_proof_of_no_policy_speech"])

    def test_explicit_utc_0430_converts_to_0030_eastern(self):
        # Screenshot's 04:30 cannot be called 04:30 ET without verified timezone.
        f=feed([event(at="2026-10-13T04:30:00+00:00")])
        f["collected_at_utc"]="2026-10-13T04:19:00+00:00"
        report=make_radar(f,now=datetime(2026,10,13,4,20,tzinfo=timezone.utc))
        self.assertEqual(report["monitored_events"][0]["event_at_et"],"2026-10-13T00:30:00-04:00")
        self.assertTrue(report["do_not_infer_calendar_timezone_from_device_clock"])

    def test_low_rated_governor_speech_is_high_research_priority(self):
        self.assertEqual(urgency("BoJ Governor Ueda speaks","Low"),
                         "HIGH_POLICY_SPEECH_OR_DECISION")
        self.assertEqual(urgency("RBA Meeting Minutes","Low"),"HIGH_POLICY_SPEECH_OR_DECISION")
        self.assertEqual(urgency("Consumer Price Index CPI","High"),"HIGH_MACRO_RELEASE_REVIEW")

    def test_event_affected_jpy_crosses_not_unrelated_audusd(self):
        wanted={"USDJPY","AUDJPY","NZDJPY","EURJPY"}
        names={p for p in ("AUDUSD","USDJPY","AUDJPY","NZDJPY","EURJPY","EURCAD") if affected(p,"JPY")}
        self.assertEqual(names,wanted)

    def test_missing_calendar_disclosed_not_empty_as_success(self):
        doc=make_radar({},now=NOW)
        self.assertEqual(doc["calendar_status"],"STALE_OR_UNAVAILABLE")
        self.assertTrue(all(p["source_coverage_incomplete"] for p in doc["pairs"].values()))

    def test_speech_post_event_is_review_not_execution(self):
        now=NOW+timedelta(minutes=20)
        report=make_radar(feed([event()]),now=now)
        row=report["pairs"]["AUDJPY"]["upcoming_or_recent_critical"][0]
        self.assertEqual(row["event_window"],"POST_EVENT_30_MIN")
        self.assertIn("per_pair_closed_15m_event_reaction",row)
        self.assertIsNone(row["actual"])
        self.assertTrue(row["actual_not_verified_by_weekly_calendar"])

if __name__=="__main__":unittest.main()
