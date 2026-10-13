"""Offline regressions for GitHub-only free candle scan schedule."""
import unittest
from datetime import datetime,timezone
from pathlib import Path
from fx_github_slot import missed_since,slot_open
UTC=timezone.utc

class FreeGitHubSlotTests(unittest.TestCase):
    def test_free_cron_exactly_four_slots_and_no_code_push_scan(self):
        workflow=Path(".github/workflows/rotation.yml").read_text(encoding="utf-8")
        header=workflow.split("permissions:",1)[0]
        self.assertIn("cron: '2,17,32,47 * * * *'",header)
        self.assertNotIn("  push:",header)
        self.assertNotIn("'2,7,12,17",header)
        self.assertIn("python fx_github_slot.py collect",workflow)
        self.assertIn("python fx_github_slot.py finalize",workflow)
        self.assertIn("python fx_github_slot.py record",workflow)
        self.assertIn("Fail missed scheduled slots visibly",workflow)
        self.assertIn("git add fx_scan_health.json fx_scan_slot_history.json",workflow)
        self.assertFalse(Path("render.yaml").exists())

    def test_unrecorded_open_market_15m_slot_is_flagged_not_backfilled(self):
        older=[{"scheduled_for_utc":"2026-10-13T20:17:00+00:00",
                "status":"FULL_REPORT_EXACT_CANDLES_VERIFIED"}]
        current=datetime(2026,10,13,20,47,tzinfo=UTC)
        missed=missed_since(older,current)
        self.assertEqual([s["scheduled_for_utc"] for s in missed],
                        ["2026-10-13T20:32:00+00:00"])
        self.assertFalse(missed[0]["signal_publication_allowed"])
        self.assertTrue(missed[0]["not_a_replayed_or_backfilled_signal"])

    def test_no_older_record_means_no_invented_missed_scan(self):
        self.assertEqual(missed_since([],datetime(2026,10,13,20,17,tzinfo=UTC)),[])

    def test_market_closed_slots_are_not_reported_as_tradeable(self):
        self.assertFalse(slot_open({"candle_slot_close_utc":"2026-10-17T20:15:00+00:00"}))
        self.assertTrue(slot_open({"candle_slot_close_utc":"2026-10-13T20:15:00+00:00"}))

    def test_policy_has_no_orders_or_external_paid_service(self):
        workflow=Path(".github/workflows/rotation.yml").read_text()
        self.assertIn("No", "No orders")
        self.assertNotIn("fx_external_scan.py",workflow)
        self.assertNotIn("Render",workflow)

if __name__=="__main__":unittest.main()
