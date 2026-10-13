"""Offline tests for central-bank headline visibility, no-hindsight and source scope."""
import unittest
from datetime import datetime,timezone,timedelta
from fx_news_priority import make_watch,headline_priority,completed_event_reaction,enrich_with_closed_reactions
from fx_macro_collector import NEWS_URLS
NOW=datetime(2026,10,13,9,10,tzinfo=timezone.utc)
ARTICLE={"title":"BoJ officials reportedly lean against October interest rate hike",
         "url":"https://www.fxstreet.com/news/illustrative-policy-item",
         "published_at_utc":"2026-10-13T08:45:00+00:00",
         "currencies":["JPY"]}

class NewsPriorityTests(unittest.TestCase):
    def feeds(self, article=ARTICLE):
        return {"FXStreet_RSS":{"status":"DATED_HEADLINES","articles":[article]},
                "Reuters_currency_page":{"status":"UNAVAILABLE_HTTPERROR","articles":[]}}

    def test_boj_regression_catches_445_and_maps_all_jpy_crosses(self):
        doc=make_watch(self.feeds(),now=NOW)
        h=doc["recent_headlines"][0]
        self.assertEqual(h["publisher_age_minutes"],25)
        self.assertEqual(h["priority"],"HIGH_POLICY_REACTION_CHECK")
        self.assertEqual(set(h["affected_pairs"]),{"USDJPY","AUDJPY","NZDJPY","EURJPY"})
        self.assertEqual(h["headline_direction"],"UNDETERMINED")
        self.assertEqual(doc["pairs"]["AUDJPY"]["status"],"POLICY_REACTION_CHECK")
        self.assertFalse(doc["pairs"]["AUDJPY"]["price_reaction_requires_completed_15m30m_candles"] is False)
        self.assertTrue(doc["any_provider_unavailable"])

    def test_4_45_boj_first_red_then_green_reversal_is_not_hindsight_alert(self):
        # Synthetic source times: server 3h ahead of true UTC. The 4:45 ET
        # policy headline at 08:45 UTC is followed by 09:00 and 09:15 closes.
        import calendar
        def source_open(hour, minute):
            return calendar.timegm(datetime(2026,10,13,hour,minute,
                                            tzinfo=timezone.utc).timetuple())+10800
        fetched=datetime(2026,10,13,9,20,tzinfo=timezone.utc)
        v={"collected_at_utc":fetched.isoformat(),
           "source_timestamp":fetched.timestamp()+10800,
           "pairs":{"AUDJPY":{"tf":{"M15":{
               "t":[source_open(8,15),source_open(8,30),
                    source_open(8,45),source_open(9,0)],
               "c":[110.190,110.158,110.047,110.162]}}}}}
        result=completed_event_reaction(v,"AUDJPY",
             "2026-10-13T08:45:00+00:00","2026-10-13T09:10:00+00:00")
        self.assertEqual(result["status"],"FIRST_MOVE_REVERSED_ON_SECOND_M15")
        self.assertEqual(result["first_post_event_change_pips"],-11.1)
        self.assertEqual(result["second_post_event_change_pips"],11.5)
        self.assertEqual(result["net_two_bar_event_window_pips"],0.4)
        self.assertFalse(result["causal_link_verified"])
        self.assertFalse(result["first_seen_before_market_reaction"])
        self.assertTrue(result["retrospective_if_first_seen_after_first_candle"])
        watch=make_watch(self.feeds(),now=NOW)
        enriched=enrich_with_closed_reactions(watch,v)
        self.assertEqual(enriched["pairs"]["AUDJPY"]["policy_headlines"][0]
                         ["price_reaction_observation"]["status"],
                         "FIRST_MOVE_REVERSED_ON_SECOND_M15")

    def test_no_new_publisher_or_invented_trade(self):
        doc=make_watch(self.feeds(),now=NOW)
        self.assertEqual(set(NEWS_URLS),{"FXStreet_RSS","Reuters_currency_page"})
        self.assertFalse(doc["no_new_sources"])
        self.assertTrue(doc["no_unapproved_sources"])
        self.assertIn("Newsquawk_public_delayed",doc["approved_source_names"])
        self.assertTrue(doc["no_headline_buy_sell_votes"])
        self.assertTrue(doc["no_trades_or_alerts"])

    def test_source_absence_must_not_be_interpreted_as_no_news(self):
        doc=make_watch({},now=NOW)
        self.assertTrue(doc["any_provider_unavailable"])
        self.assertTrue(doc["pairs"]["AUDJPY"]["no_news_is_not_proof_of_no_catalyst"])

    def test_old_future_and_unverified_times_rejected(self):
        for p in [(NOW+timedelta(minutes=15)).isoformat(),
                  (NOW-timedelta(minutes=121)).isoformat(),None]:
            self.assertIsNone(headline_priority({**ARTICLE,"published_at_utc":p},NOW))

    def test_preserve_first_seen_across_scans(self):
        initial=make_watch(self.feeds(),now=NOW)
        next_scan=make_watch(self.feeds(),previous=initial,now=NOW+timedelta(minutes=5))
        self.assertEqual(next_scan["recent_headlines"][0]["first_seen_at_utc"],NOW.isoformat())
        self.assertEqual(next_scan["recent_headlines"][0]["source_latency_to_first_seen_minutes"],25)

    def test_hawkish_and_dovish_bojs_both_require_price_evidence(self):
        for title in ("BoJ leaning against back to back hikes",
                      "BoJ governor favors additional interest rate hike"):
            item=headline_priority({**ARTICLE,"title":title},NOW)
            self.assertEqual(item["headline_direction"],"UNDETERMINED")
            self.assertEqual(item["market_reaction"],"NOT_VERIFIED")

    def test_rba_maps_aud_not_unrelated_crosses(self):
        item=headline_priority({**ARTICLE,"title":"RBA discusses rate hike",
                                "currencies":["AUD"]},NOW)
        self.assertIn("AUDJPY",item["affected_pairs"])
        self.assertNotIn("USDJPY",item["affected_pairs"])

if __name__=="__main__":
    unittest.main()
