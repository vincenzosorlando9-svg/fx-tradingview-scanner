"""Offline tests for the audit collector; no network access required."""
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("fx_audit_engine",ROOT/"engine.py")
engine=importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

class FakeResponse:
    status=200
    headers={"Content-Type":"text/html"}
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,n): return b"test payload"

class AuditTests(unittest.TestCase):
    def test_registry_unique_https(self):
        sources=json.loads((ROOT/"sources.json").read_text())
        self.assertEqual(len(sources),73)
        self.assertEqual(len({x["id"] for x in sources}),len(sources))
        self.assertTrue(all(x["url"].startswith("https://") for x in sources))
        self.assertEqual(len([x for x in sources if x["id"]=="oilprice"]),1)

    @patch.object(engine.urllib.request,"urlopen",return_value=FakeResponse())
    def test_http_success_is_not_verified_data(self,open_mock):
        result=engine.fetch({"id":"test","url":"https://example.com"} ,1)
        self.assertEqual(result["status"],"retrieved")
        self.assertIs(result["data_verified"],False)
        self.assertIsNone(result["source_observation_time"])
        self.assertTrue(result["attempted_at_et"])
        open_mock.assert_called_once()

    @patch.object(engine.urllib.request,"urlopen",side_effect=urllib.error.HTTPError("https://example.com",403,"Forbidden",None,None))
    def test_blocked_source_is_logged_not_silently_skipped(self,_):
        result=engine.fetch({"id":"test","url":"https://example.com"},1)
        self.assertEqual(result["status"],"http_error")
        self.assertEqual(result["http_status"],403)
        self.assertIs(result["data_verified"],False)

if __name__=="__main__":unittest.main()
