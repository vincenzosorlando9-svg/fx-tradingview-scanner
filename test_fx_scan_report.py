"""Regression tests for the user's full FOREX MAIN SIGNAL — 15-LAYER MACRO-FIRST AUDIT."""
import unittest
from datetime import datetime, timezone
from fx_macro_collector import PAIRS
from fx_scan_report import (build_report, render_markdown, PRESENTATION_ORDER,
                            LAYER_TITLES, LAYOUT_VERSION, candles_only_closed)

class ScanReportLayoutTests(unittest.TestCase):
    def fixtures(self):
        rows=[]
        for i,pair in enumerate(PAIRS):
            rows.append({
                "pair":pair, "direction":"BUY" if i%2==0 else "SELL",
                "technical_stage":"EARLY" if i<3 else "CONFIRMING",
                "trade_execution_allowed":False,
                "technical_research_rank_score":round(1-i*.05,2),
                "entry":None,"stop":None,"tp1":None,"tp2":None,
                "reference_prices":{"last_closed_15m":1.0+i*.01,
                                    "closed_at_utc":"2026-10-13T12:00:00+00:00"},
                "why_now_evidence":[{"type":"TECHNICAL","observations":["test"]}]})
        united={"all_11":rows, "top_five":rows[:5],
                "generated_at_utc":"2026-10-13T12:01:00+00:00",
                "source_technical_generated_at_utc":"2026-10-13T12:00:00+00:00",
                "signals_from":"CLOSED_15M_30M_ONLY"}
        dashboard={"generated_at_utc":"2026-10-13T12:00:00+00:00",
                   "currency_strength_breadth":{"AUD":3,"NZD":2,"EUR":1,
                                                "GBP":0,"USD":-3,"JPY":-2,"CAD":-1},
                   "currency_strength_note":"Technical breadth, not true live index"}
        return united,dashboard

    def sample_feed(self, pair="EURUSD", m15=None, m30=None, collected="2026-10-13T12:03:00+00:00"):
        base=1791891000  # October 13 2026 11:30 UTC
        bars15=m15 or [1.1000,1.1010,1.1020]
        bars30=m30 or [1.1000,1.1010,1.1020]
        # 11:30, 11:45, 12:00 opens; 12:00 last bar forming at 12:03.
        # Published unified 12:01 => latest closed 11:45 if timestamps align.
        return {"collected_at_utc":collected,
                "pairs":{pair:{"tf":{
                    "M15":{"t":[base,base+900,base+1800], "c":bars15,
                           "h":[x+.0005 for x in bars15],
                           "l":[x-.0005 for x in bars15]},
                    "M30":{"t":[base-1800,base,base+1800], "c":bars30,
                           "h":[x+.0005 for x in bars30],
                           "l":[x-.0005 for x in bars30]}}}}}

    def test_exact_top_level_order_and_all_fifteen_layers(self):
        u,d=self.fixtures()
        report=build_report(u,d)
        self.assertEqual(list(report),PRESENTATION_ORDER)
        self.assertEqual(report["layout_contract"]["version"],LAYOUT_VERSION)
        self.assertTrue(report["layout_contract"]["default_locked_until_user_explicitly_changes_it"])
        self.assertTrue(report["layout_contract"]["do_not_simplify_to_six_sections"])
        self.assertEqual(len(report["fifteen_layer_macro_first_audit"]),15)
        self.assertEqual([v["title"] for v in report["fifteen_layer_macro_first_audit"]],LAYER_TITLES)
        self.assertEqual(len(report["full_15_layer_coverage_audit"]),15)
        self.assertEqual(report["report_header"]["title"],
                         "FOREX MAIN SIGNAL — 15-LAYER MACRO-FIRST AUDIT")

    def test_strength_then_top_five_plus_all_eleven(self):
        report=build_report(*self.fixtures())
        self.assertEqual(report["current_currency_strength"]["strongest"],["AUD"])
        self.assertEqual(report["current_currency_strength"]["weakest"],["USD"])
        self.assertEqual(len(report["top_five_published_ranking"]["rows"]),5)
        self.assertEqual(len(report["fifteen_layer_macro_first_audit"][10]["pairs"]),11)

    def test_no_broker_quote_or_invented_stop_target(self):
        report=build_report(*self.fixtures())
        layer14=report["fifteen_layer_macro_first_audit"][13]
        first=layer14["per_pair_conditional_research_criteria"][0]
        self.assertIsNone(first["entry"])
        self.assertIsNone(first["stop"])
        self.assertIsNone(first["tp1"])
        self.assertIsNone(first["tp2"])
        self.assertFalse(first["broker_executable"])
        self.assertFalse(layer14["precise_entries_stops_and_targets_independently_verified"])

    def test_missing_currency_strength_is_not_guessed(self):
        u,d=self.fixtures()
        d["currency_strength_breadth"].pop("USD")
        report=build_report(u,d)
        self.assertEqual(report["current_currency_strength"]["status"],
                         "UNAVAILABLE_INCOMPLETE_BREADTH")
        self.assertEqual(report["current_currency_strength"]["strongest"],[])
        self.assertTrue(all(row["breadth_score"] is None for row in
                            report["current_currency_strength"]["ranked_strongest_to_weakest"]))

    def test_mismatched_published_sources_refused(self):
        u,d=self.fixtures()
        d["generated_at_utc"]="2026-10-13T11:00:00+00:00"
        with self.assertRaisesRegex(ValueError,"SOURCE_TIMES"):
            build_report(u,d)

    def test_bad_pair_universe_refused(self):
        u,d=self.fixtures()
        u["all_11"].pop()
        with self.assertRaisesRegex(ValueError,"ALL_11"):
            build_report(u,d)

    def test_original_direction_and_rank_remain_unmodified(self):
        u,d=self.fixtures()
        saved=[(r["pair"],r["direction"],r["technical_research_rank_score"])
               for r in u["all_11"]]
        report=build_report(u,d)
        self.assertEqual([(r["pair"],r["direction"],r["technical_research_rank_score"])
                          for r in u["all_11"]],saved)
        self.assertEqual([r["pair"] for r in report["top_five_published_ranking"]["rows"]],
                         [r["pair"] for r in u["top_five"]])

    def test_more_recent_candles_cannot_rewrite_old_rank(self):
        u,d=self.fixtures()
        # Full sample includes one extra currency for testing a strong counterrotation.
        pair=PAIRS[5]
        self.assertEqual(pair,"AUDJPY")
        u["all_11"][5]["direction"]="BUY"
        v=self.sample_feed(pair=pair,
                           m15=[110.32,110.28,110.20],
                           m30=[110.41,110.35,110.20])
        report=build_report(u,d,volatility=v)
        rank=report["top_five_published_ranking"]["rows"]
        self.assertEqual([r["pair"] for r in rank],list(PAIRS)[:5])
        self.assertTrue(all(r["published_ranking_preserved"] for r in rank))
        self.assertEqual(report["fifteen_layer_macro_first_audit"][10]["pairs"][5]["original_published_direction"],"BUY")

    def test_completed_candles_exclude_forming_bar(self):
        # 11:30 open, 11:45 open, 12:00 open, collection 12:03 UTC.
        v=self.sample_feed(m15=[1.1000,1.1010,1.9999])
        out=candles_only_closed(v,"EURUSD","M15",v["collected_at_utc"])
        self.assertEqual(out["status"],"SITE_REPORTED_COMPLETED_CANDLE")
        self.assertAlmostEqual(out["close"],1.1010)
        self.assertNotEqual(out["close"],1.9999)

    def test_markdown_has_every_numbered_section_and_coverage(self):
        report=build_report(*self.fixtures())
        md=render_markdown(report)
        self.assertIn("# FOREX MAIN SIGNAL — 15-LAYER MACRO-FIRST AUDIT",md)
        for i,title in enumerate(LAYER_TITLES,1):
            self.assertIn("## "+str(i)+". "+title,md)
        self.assertIn("## FULL 15-LAYER COVERAGE AUDIT",md)
        self.assertIn("## FINAL FOREX MAIN SIGNAL",md)
        self.assertIn("CURRENT CURRENCY STRENGTH",md)
        self.assertIn("CRITICAL SETUPS OMITTED FROM TOP FIVE",md)
        self.assertNotIn("## five_detailed_trade_setups",md)

if __name__=="__main__":
    unittest.main()
