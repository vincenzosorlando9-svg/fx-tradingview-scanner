"""Tests that the user-approved currency-strength-first layout cannot drift."""
import unittest
from fx_macro_collector import PAIRS
from fx_scan_report import build_report, PRESENTATION_ORDER, LAYOUT_VERSION

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
                "why_now_evidence":["test evidence"]})
        united={"all_11":rows, "top_five":rows[:5],
                "generated_at_utc":"2026-10-13T12:01:00+00:00",
                "source_technical_generated_at_utc":"2026-10-13T12:00:00+00:00",
                "signals_from":"CLOSED_15M_30M_ONLY"}
        dashboard={"generated_at_utc":"2026-10-13T12:00:00+00:00",
                   "currency_strength_breadth":{"AUD":3,"NZD":2,"EUR":1,
                                                "GBP":0,"USD":-3,"JPY":-2,"CAD":-1},
                   "currency_strength_note":"Technical breadth, not true live index"}
        return united,dashboard

    def test_fixed_order_and_breadth_ranking(self):
        report=build_report(*self.fixtures())
        self.assertEqual(list(report)[:6],PRESENTATION_ORDER)
        self.assertEqual(report["layout_contract"]["version"],LAYOUT_VERSION)
        self.assertTrue(report["layout_contract"]["default_locked_until_user_explicitly_changes_it"])
        self.assertEqual(report["currency_strength"]["strongest"],["AUD"])
        self.assertEqual(report["currency_strength"]["weakest"],["USD"])
        self.assertEqual(len(report["best_five_trading_pairs"]),5)
        self.assertEqual(len(report["all_11_pairs"]),11)

    def test_no_invented_orders_prices_or_stops(self):
        report=build_report(*self.fixtures())
        first=report["five_detailed_trade_setups"][0]
        self.assertIsNone(first["conditional_entry"])
        self.assertIsNone(first["stop_or_invalidation"])
        self.assertIsNone(first["tp1"])
        self.assertIsNone(first["tp2"])
        self.assertFalse(first["trade_execution_allowed"])
        self.assertEqual(first["price_type"],"LAST_CLOSED_15M_REFERENCE_NOT_EXECUTABLE")
        self.assertEqual(report["complete_market_intelligence"]["technical_analysis_and_levels"]["excluded_from_signals"],["5m"])

    def test_missing_breadth_never_manufactures_strength(self):
        u,d=self.fixtures()
        d["currency_strength_breadth"].pop("USD")
        report=build_report(u,d)
        self.assertEqual(report["currency_strength"]["status"],"UNAVAILABLE_INCOMPLETE_BREADTH")
        self.assertEqual(report["currency_strength"]["strongest"],[])
        self.assertTrue(all(x["breadth_score"] is None
                            for x in report["currency_strength"]["ranked_strongest_to_weakest"]))

    def test_mismatched_timestamps_refused(self):
        u,d=self.fixtures()
        d["generated_at_utc"]="2026-10-13T11:00:00+00:00"
        with self.assertRaisesRegex(ValueError,"SOURCE_TIMES"):
            build_report(u,d)

    def test_invalid_pair_universe_refused(self):
        u,d=self.fixtures()
        u["all_11"].pop()
        with self.assertRaisesRegex(ValueError,"ALL_11"):
            build_report(u,d)

    def test_direction_and_rank_are_not_mutated(self):
        u,d=self.fixtures()
        original=[(r["pair"],r["direction"],r["technical_research_rank_score"])
                  for r in u["all_11"]]
        report=build_report(u,d)
        self.assertEqual([(r["pair"],r["direction"],r["technical_research_rank_score"])
                          for r in u["all_11"]],original)
        self.assertEqual([r["pair"] for r in report["best_five_trading_pairs"]],
                         [r["pair"] for r in u["top_five"]])

if __name__=="__main__":
    unittest.main()
