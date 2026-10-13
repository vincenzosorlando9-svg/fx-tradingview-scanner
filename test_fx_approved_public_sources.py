"""Public FX Blue and Newsquawk parser tests: no clocks or access invented."""
import unittest
from datetime import datetime,timezone
from fx_approved_public_sources import (
    parse_fx_blue,parse_newsquawk_article,parse_newsquawk_index,
    collect_newsquawk,FX_BLUE,NEWSQUAWK)
from fx_calendar_priority import make_radar
from fx_news_priority import make_watch
NOW=datetime(2026,10,13,9,10,tzinfo=timezone.utc)
UTC=NOW.isoformat()
def page(url,body,status="OK"):
    return {"url":url,"retrieved_at_utc":UTC,"http_status":status,"body":body}
CALENDAR="""<html><h2>Key Events: Next 7 Days</h2><table>
<tr><th>Time (UTC)</th><th>Currency</th><th>Event</th><th>Importance</th></tr>
<tr><td>Tue 13 Oct, 04:30</td><td>JPY</td><td>BoJ Governor Ueda speech</td><td>High</td></tr>
<tr><td>Tue 13 Oct, 00:30</td><td>AUD</td><td>RBA Meeting Minutes</td><td>High</td></tr>
</table></html>"""
NEWS_ARTICLE="""<html><h1>BoJ is reportedly to lean back against back-to-back hikes in October</h1>
<div>Newsquawk Staff/Published 13 Oct 2026, 09:05 UTC</div>
<div>On the Newsquawk feed at 08:45, 20 minutes before this page.</div></html>"""
NEWS_INDEX="""<a href='/headlines/boj-is-reportedly-to-lean-back-against-back-to-back-hikes-in-october'>BoJ is reportedly to lean back against back-to-back hikes in October</a>"""

class ApprovedPublicSourcesTests(unittest.TestCase):
    def test_fxblue_utc_and_speech(self):
        result=parse_fx_blue(page(FX_BLUE,CALENDAR))
        self.assertEqual(result["status"],"DATED_UTC_PUBLIC_EVENTS")
        self.assertEqual(len(result["events"]),2)
        self.assertEqual(result["events"][0]["event_at_utc"],"2026-10-13T00:30:00+00:00")
        speech=result["events"][1]
        self.assertEqual(speech["currency"],"JPY")
        self.assertEqual(speech["event_at_utc"],"2026-10-13T04:30:00+00:00")
        self.assertEqual(speech["title"],"BoJ Governor Ueda speech")
        self.assertEqual(speech["impact"],"High")

    def test_no_explicit_utc_table_is_not_scheduled(self):
        result=parse_fx_blue(page(FX_BLUE,CALENDAR.replace("Time (UTC)","Local Time")))
        self.assertEqual(result["status"],"UNAVAILABLE_NO_EXPLICIT_UTC_EVENT_TABLE")
        self.assertEqual(result["events"],[])

    def test_newsquawk_uses_delayed_publication_not_early_professional_feed(self):
        result=parse_newsquawk_article(page(NEWSQUAWK+"/boj-is-reportedly-to-lean-back-against-back-to-back-hikes-in-october",NEWS_ARTICLE))
        self.assertIsNotNone(result)
        self.assertEqual(result["published_at_utc"],"2026-10-13T09:05:00+00:00")
        self.assertEqual(result["public_delay_at_least_minutes"],20)
        self.assertEqual(result["currencies"],["JPY"])
        self.assertNotEqual(result["published_at_utc"],"2026-10-13T08:45:00+00:00")

    def test_newsquawk_no_absolute_dated_clock_no_headline(self):
        result=parse_newsquawk_article(page(NEWSQUAWK+"/boj-claim",
                              NEWS_ARTICLE.replace("Published 13 Oct 2026, 09:05 UTC","Posted 3 mins ago")))
        self.assertIsNone(result)

    def test_newsquawk_public_index_and_url_restriction(self):
        self.assertEqual(len(parse_newsquawk_index(page(NEWSQUAWK,NEWS_INDEX))),1)
        self.assertEqual(parse_newsquawk_index(page(NEWSQUAWK,NEWS_INDEX.replace(
             "/headlines/","https://not-newsquawk.example/headlines/"))),[])

    def test_newsquawk_integrated_as_new_approved_delayed_news_provider(self):
        article=parse_newsquawk_article(page(NEWSQUAWK+"/boj-claim",NEWS_ARTICLE))
        sources={"Newsquawk_public_delayed":{"status":"DATED_HEADLINES","articles":[article]}}
        doc=make_watch(sources,now=NOW)
        self.assertEqual(doc["pairs"]["AUDJPY"]["status"],"POLICY_REACTION_CHECK")
        self.assertIn("Newsquawk_public_delayed",doc["approved_source_names"])
        self.assertTrue(doc["no_unapproved_sources"])
        self.assertTrue(doc["no_trades_or_alerts"])
        self.assertIn("Reuters_currency_page:UNAVAILABLE",doc["source_coverage_gaps"])

    def test_fxblue_adds_missing_ueda_event_even_when_ff_empty(self):
        b=parse_fx_blue(page(FX_BLUE,CALENDAR))
        empty={"status":"VERIFIED","collected_at_utc":UTC,
               "events":[{"title":"Existing Home Sales","currency":"USD","event_at_utc":"2026-10-13T14:00:00+00:00","impact":"Low"}]}
        doc=make_radar(empty,now=NOW,fx_blue=b)
        self.assertEqual(doc["calendar_status"],"FRESH_FF_PLUS_FXBLUE")
        self.assertEqual(doc["fx_blue_verified_utc_events"],2)
        self.assertIn("BoJ Governor Ueda speech",
                      [x["title"] for x in doc["monitored_events"]])
        self.assertEqual(doc["pairs"]["AUDJPY"]["directional_vote"],"NONE")
        self.assertTrue(doc["no_orders_or_alerts"])

if __name__=="__main__":unittest.main()
