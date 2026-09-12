"""工具调用 trace 的缓存、持久化和脱敏测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from ..tools.trace import ToolTracer


class TestToolTracer(unittest.TestCase):
    def test_ring_buffer_keeps_latest_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tracer = ToolTracer(Path(temp_dir) / "trace.jsonl", memory_limit=2)
            tracer.record("first", {}, "ok", 1)
            tracer.record("second", {}, "ok", 2)
            tracer.record("third", {}, "ok", 3)
            self.assertEqual([item["tool"] for item in tracer.entries], ["second", "third"])

            snapshot = tracer.entries
            snapshot.clear()
            self.assertEqual(len(tracer.entries), 2)

    def test_record_redacts_secrets_and_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "trace.jsonl"
            tracer = ToolTracer(log_path)
            entry = tracer.record(
                "web_search",
                {"query": "agent", "api_token": "secret-value"},
                "line 1\nline 2",
                12.34,
            )

            self.assertEqual(entry["input"]["api_token"], "***")
            self.assertTrue(entry["ts"].endswith("Z"))
            self.assertNotIn("\n", entry["result_preview"])
            persisted = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(persisted["input"]["api_token"], "***")

    def test_recent_rejects_non_positive_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tracer = ToolTracer(Path(temp_dir) / "trace.jsonl")
            tracer.record("calculator", {}, "1+1 = 2", 1)
            self.assertEqual(tracer.recent(0), [])
            self.assertEqual(tracer.recent(-1), [])

    def test_memory_limit_must_be_positive_integer(self):
        with self.assertRaises(ValueError):
            ToolTracer(memory_limit=0)
        with self.assertRaises(ValueError):
            ToolTracer(memory_limit=True)


if __name__ == "__main__":
    unittest.main()
