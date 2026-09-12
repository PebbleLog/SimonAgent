"""记忆压缩的完整性与工具协议边界测试。"""
import unittest
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ..core import compactor as compactor_module
from ..core.memory import MemoryStore


class FakeMemory:
    def __init__(self):
        self.writes = []

    def read_memory(self):
        return "旧记忆"

    def read_user(self):
        return "旧画像"

    def read_today_episode(self):
        return ""

    def append_episode(self, text):
        self.writes.append(("episode", text))
        return True

    def write_memory(self, text):
        self.writes.append(("memory", text))
        return True

    def write_user(self, text):
        self.writes.append(("user", text))
        return True


class FakeCreateMessages:
    def __init__(self, text):
        self.text = text

    def create(self, **_kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


class FakeCreateClient:
    def __init__(self, text):
        self.messages = FakeCreateMessages(text)


def dialogue(turns=8):
    history = []
    for i in range(turns):
        history.extend([
            {"role": "user", "content": f"问题{i}"},
            {"role": "assistant", "content": [{"type": "text", "text": f"回答{i}"}]},
        ])
    return history


class TestCompactorSafety(unittest.TestCase):
    def _compact(self, response):
        history = dialogue()
        memory = FakeMemory()
        with patch.object(compactor_module, "client", FakeCreateClient(response)), \
             patch.object(compactor_module, "MEMORY", memory), \
             patch.object(compactor_module, "COMPACT_AFTER_MESSAGES", 2):
            result = compactor_module.compact_history(history)
        return history, result, memory

    def test_incomplete_model_output_keeps_full_history(self):
        history, result, memory = self._compact("<episode>只有一段</episode>")
        self.assertEqual(result, history)
        self.assertEqual(memory.writes, [])

    def test_complete_model_output_updates_all_memories(self):
        response = (
            "<episode>摘要</episode>"
            "<updated_memory>新记忆</updated_memory>"
            "<updated_user>新画像</updated_user>"
        )
        history, result, memory = self._compact(response)
        self.assertLess(len(result), len(history))
        self.assertEqual([kind for kind, _ in memory.writes], ["memory", "user", "episode"])
        self.assertEqual(result[0]["role"], "user")
        self.assertIsInstance(result[0]["content"], str)

    def test_memory_store_commits_three_compaction_outputs(self):
        root = Path(tempfile.mkdtemp())
        try:
            memory = MemoryStore(root / "memory", root / "templates")
            self.assertTrue(memory.commit_compaction("新记忆", "新画像", "新情景"))
            snapshot = memory.snapshot()
            self.assertEqual(snapshot.long_term.strip(), "新记忆")
            self.assertEqual(snapshot.user_profile.strip(), "新画像")
            self.assertIn("新情景", snapshot.today_episode)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_templates_seed_runtime_memory_without_being_overwritten(self):
        root = Path(tempfile.mkdtemp())
        try:
            templates = root / "templates"
            templates.mkdir()
            (templates / "MEMORY.md").write_text("初始记忆\n", encoding="utf-8")
            (templates / "USER.md").write_text("初始画像\n", encoding="utf-8")
            memory = MemoryStore(root / "memory", templates)

            self.assertEqual(memory.read_memory(), "初始记忆\n")
            self.assertEqual(memory.read_user(), "初始画像\n")
            self.assertTrue(memory.write_user("运行时画像"))
            self.assertEqual((templates / "USER.md").read_text(encoding="utf-8"), "初始画像\n")
            self.assertEqual((root / "memory" / "USER.md").read_text(encoding="utf-8"), "运行时画像\n")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
