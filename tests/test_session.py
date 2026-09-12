"""Session 的创建、持久化、隔离、切换与损坏数据测试。"""
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ..core.exceptions import SessionNotFoundError
from ..core.session import Session, SessionManager


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sm = SessionManager(sessions_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_session(self, text: str):
        s = self.sm.create()
        s.history.append({"role": "user", "content": text})
        self.sm.save(s)
        return s

    def test_create_and_persist(self):
        s = self._make_session("第一条消息")
        self.assertTrue((self.tmp / f"{s.id}.json").exists())
        self.assertIsNotNone(datetime.fromisoformat(s.created_at).tzinfo)

    def test_sessions_are_isolated(self):
        """两个会话的 history 互不干扰。"""
        s1 = self._make_session("查天气记待办")
        s2 = self._make_session("写周报记待办")
        s1_back = self.sm.load(s1.id)
        contents = str(s1_back.history)
        self.assertIn("查天气", contents)
        self.assertNotIn("写周报", contents)
        self.assertNotEqual(s1.id, s2.id)

    def test_prefix_switch(self):
        s = self._make_session("前缀测试")
        loaded = self.sm.load(s.id[:18])
        self.assertEqual(loaded.id, s.id)
        self.assertEqual(loaded.history[0]["content"], "前缀测试")

    def test_load_not_found(self):
        with self.assertRaises(SessionNotFoundError):
            self.sm.load("not-exist")

    def test_path_traversal_blocked(self):
        with self.assertRaises(SessionNotFoundError):
            self.sm.load("../evil")

    def test_invalid_id_cannot_be_saved(self):
        session = Session(id="../evil", created_at="", history=[])
        with self.assertRaises(SessionNotFoundError):
            self.sm.save(session)

    def test_corrupt_structure_is_reported_consistently(self):
        path = self.tmp / "broken.json"
        path.write_text(json.dumps({"id": "broken", "history": "not-a-list"}), encoding="utf-8")
        with self.assertRaises(SessionNotFoundError):
            self.sm.load("broken")

    def test_list_skips_filename_id_mismatch(self):
        path = self.tmp / "expected.json"
        path.write_text(
            json.dumps({"id": "different", "created_at": "", "history": []}),
            encoding="utf-8",
        )
        self.assertEqual(self.sm.list(), [])

    def test_reload_after_restart(self):
        """模拟重启：新 SessionManager 实例能恢复全部会话。"""
        self._make_session("会话A")
        self._make_session("会话B")
        sm2 = SessionManager(sessions_dir=self.tmp)
        self.assertEqual(len(sm2.list()), 2)

    def test_preview_uses_first_user_message(self):
        s = self._make_session("这是首条用户消息")
        sessions = self.sm.list()
        self.assertIn("首条用户消息", sessions[0].preview())


if __name__ == "__main__":
    unittest.main()
