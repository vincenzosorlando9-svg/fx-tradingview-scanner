"""Offline regressions for GitHub-only free candle scan schedule."""
import json
import os
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
import fx_github_slot as runner
from fx_exact_candle_gate import expected_slot
from fx_github_slot import missed_since,slot_open,verified_existing_slot
UTC=timezone.utc

class FreeGitHubSlotTests(unittest.TestCase):
    def test_free_cron_exactly_four_slots_and_no_code_push_scan(self):
        workflow=Path(".github/workflows/rotation.yml").read_text(encoding="utf-8")
        header=workflow.split("permissions:",1)[0]
        self.assertIn("cron: '2,17,32,47 * * * *'",header)
        self.assertIn("cron: '5,20,35,50 * * * *'",header)
        self.assertIn("FX_SCAN_CRON: ${{ github.event.schedule }}",workflow)
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

    @staticmethod
    def published_fixture(slot):
        stamp=slot["candle_slot_close_utc"]
        published="2026-10-13T22:32:25+00:00"
        row={"status":"FULL_REPORT_EXACT_CANDLES_VERIFIED",
             "scheduled_for_utc":slot["scheduled_for_utc"],
             "expected_candle_close_utc":stamp,
             "signal_publication_allowed":True,"validated_pairs":11,
             "expected_closes":{"M15":stamp,"M30":"2026-10-13T22:30:00+00:00",
                                "H1":"2026-10-13T22:00:00+00:00"},
             "unified_generated_at_utc":published,"trigger_event":"schedule",
             "is_scheduled_trigger":True}
        signal={"generated_at_utc":published,
                "all_11":[{"reference_prices":{"closed_at_utc":stamp}} for _ in range(11)]}
        return row,signal

    def test_backup_skips_validated_primary_only_on_exact_identical_slot(self):
        slot=expected_slot(datetime(2026,10,13,22,35,tzinfo=UTC))
        prior,unified=self.published_fixture(slot)
        self.assertTrue(verified_existing_slot(slot,{"slots":[prior]},unified))
        manual=dict(prior,trigger_event="push",is_scheduled_trigger=False)
        self.assertFalse(verified_existing_slot(slot,{"slots":[manual]},unified))
        wrong=dict(unified,all_11=[
            {"reference_prices":{"closed_at_utc":"2026-10-13T22:15:00+00:00"}}
            for _ in range(11)])
        self.assertFalse(verified_existing_slot(slot,{"slots":[prior]},wrong))
        wrong_ver=dict(prior,unified_generated_at_utc="2026-10-13T22:30:00+00:00")
        self.assertFalse(verified_existing_slot(slot,{"slots":[wrong_ver]},unified))

    def test_backup_duplicate_success_does_not_run_collector_or_publish(self):
        at=datetime(2026,10,13,22,35,tzinfo=UTC)
        slot=expected_slot(at)
        primary,signals=self.published_fixture(slot)
        with tempfile.TemporaryDirectory() as td:
            health=Path(td)/"health.json"
            history=Path(td)/"history.json"
            signal_path=Path(td)/"unified.json"
            gate=Path(td)/"gate.json"
            health.write_text(json.dumps({"last_slot":primary}))
            history.write_text(json.dumps({"slots":[primary]}))
            signal_path.write_text(json.dumps(signals))
            original=health.read_text()
            old_dir=Path.cwd()
            try:
                os.chdir(td)
                with patch.object(runner,"GATE",gate),patch.object(runner,"HISTORY",history),patch.object(runner,"HEALTH",health),patch.object(runner,"now_utc",return_value=at),patch.object(runner.subprocess,"run") as run,patch.dict(os.environ,{"GITHUB_EVENT_NAME":"schedule","FX_SCAN_CRON":"5,20,35,50 * * * *"}):
                    Path("fx_unified_signals.json").write_text(json.dumps(signals))
                    self.assertEqual(runner.collect(),0)
                    self.assertEqual(json.loads(gate.read_text())["status"],"SKIP_ALREADY_VERIFIED")
                    self.assertEqual(runner.record(),None)
                    run.assert_not_called()
                    self.assertEqual(health.read_text(),original)
                    self.assertEqual(json.loads(history.read_text())["slots"],[primary])
            finally:
                os.chdir(old_dir)

    def test_backup_recovers_missing_primary_and_checks_correct_slot(self):
        at=datetime(2026,10,13,22,35,tzinfo=UTC)
        with tempfile.TemporaryDirectory() as td:
            gate=Path(td)/"gate.json"
            fake={"status":"PASS_EXACT_CLOSED_M15_M30_H1",
                  "signal_publication_allowed":True,"validated_pairs":11,
                  "source_collected_at_utc":at.isoformat(),
                  "source_clock_correction_seconds":10800,
                  "expected_closes":{"M15":"2026-10-13T22:30:00+00:00",
                                     "M30":"2026-10-13T22:30:00+00:00",
                                     "H1":"2026-10-13T22:00:00+00:00"},
                  "observed_closes":{}}
            with patch.object(runner,"GATE",gate),patch.object(runner,"now_utc",return_value=at),patch.object(runner,"verified_existing_slot",return_value=False),patch.object(runner,"validate",return_value=fake) as validator,patch.object(runner.subprocess,"run") as sub,patch.dict(os.environ,{"GITHUB_EVENT_NAME":"schedule","FX_SCAN_CRON":"5,20,35,50 * * * *"}):
                self.assertEqual(runner.collect(),0)
                rec=json.loads(gate.read_text())
                self.assertEqual(rec["scheduled_for_utc"],"2026-10-13T22:32:00+00:00")
                self.assertEqual(rec["expected_candle_close_utc"],"2026-10-13T22:30:00+00:00")
                self.assertEqual(rec["scan_trigger_type"],"backup")
                self.assertEqual(rec["status"],"EXACT_CANDLES_VERIFIED")
                validator.assert_called_once()
                sub.assert_called_once()

    def test_primary_delayed_after_backup_cannot_overwrite_verified_data(self):
        slot=expected_slot(datetime(2026,10,13,22,35,tzinfo=UTC))
        success,unified=self.published_fixture(slot)
        self.assertTrue(verified_existing_slot(slot,{"slots":[success]},unified))

    def test_failed_primary_history_preserved_after_backup_success(self):
        primary={"scheduled_for_utc":"2026-10-13T22:32:00+00:00",
                 "status":"REQUIRED_CANDLE_MISSING_DEADLINE",
                 "started_at_utc":"2026-10-13T22:33:00+00:00",
                 "trigger_event":"schedule","scan_trigger_type":"primary_or_manual"}
        backup,unified=self.published_fixture(
            expected_slot(datetime(2026,10,13,22,35,tzinfo=UTC)))
        with tempfile.TemporaryDirectory() as td:
            history=Path(td)/"history.json"
            health=Path(td)/"health.json"
            gate=Path(td)/"gate.json"
            history.write_text(json.dumps({"slots":[primary]}))
            gate.write_text(json.dumps(backup))
            with patch.object(runner,"GATE",gate),patch.object(runner,"HISTORY",history),patch.object(runner,"HEALTH",health),patch.object(runner,"now_utc",return_value=datetime(2026,10,13,22,35,tzinfo=UTC)),patch.dict(os.environ,{"PIPELINE_OUTCOME":"success","GITHUB_EVENT_NAME":"schedule","FX_SCAN_CRON":"5,20,35,50 * * * *"}):
                runner.record()
            entry=json.loads(history.read_text())["slots"][-1]
            self.assertTrue(entry["signal_publication_allowed"])
            self.assertEqual(len(entry["previous_attempts_for_slot"]),1)
            self.assertEqual(entry["previous_attempts_for_slot"][0]["status"],
                             "REQUIRED_CANDLE_MISSING_DEADLINE")

    def test_policy_has_no_orders_or_external_paid_service(self):
        workflow=Path(".github/workflows/rotation.yml").read_text()
        self.assertNotIn("fx_external_scan.py",workflow)
        self.assertNotIn("Render",workflow)

if __name__=="__main__":unittest.main()
