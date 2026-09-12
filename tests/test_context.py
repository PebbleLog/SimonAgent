"""Context 的窗口限制、工具配对、共享引用与回滚测试。"""
import shutil
import tempfile
import unittest
from pathlib import Path

from ..core import ContextManager, SessionManager
from ..core.context import estimate_tokens


def _assistant_text(t):
    return [{"type": "text", "text": t}]


def _assistant_tool_call(block_id="t1"):
    return [{"type": "text", "text": "我查一下"},
            {"type": "tool_use", "id": block_id, "name": "web_search", "input": {"query": "北京今天天气"}}]


def _tool_result(block_id="t1", content="晴 32°C"):
    return [{"type": "tool_result", "tool_use_id": block_id, "content": content}]


class TestContextFollowUp(unittest.TestCase):
    def test_pure_dialogue_follow_up(self):
        """纯对话追问：上下文保留之前的 user/assistant 文本轮次。"""
        cm = ContextManager()
        cm.add_user_message("我喜欢吃西瓜")
        cm.add_assistant_message(_assistant_text("记住了"))
        cm.add_user_message("我喜欢吃什么")  # 追问
        self.assertEqual(cm.turn_count, 2)
        self.assertEqual(cm.messages[0]["content"], "我喜欢吃西瓜")

    def test_tool_context_follow_up(self):
        """带工具的追问：tool_use/tool_result 配对完整保留，模型可见旧工具结果。"""
        cm = ContextManager()
        cm.add_user_message("北京天气怎么样")
        cm.add_assistant_message(_assistant_tool_call())
        cm.add_tool_results(_tool_result())
        cm.add_assistant_message(_assistant_text("北京晴，32°C"))
        cm.add_user_message("那上海呢")  # 带工具语境的追问

        kinds = [
            (m["role"], m["content"] if isinstance(m["content"], str)
             else [b.get("type") for b in m["content"]])
            for m in cm.messages
        ]
        self.assertEqual(kinds, [
            ("user", "北京天气怎么样"),
            ("assistant", ["text", "tool_use"]),
            ("user", ["tool_result"]),
            ("assistant", ["text"]),
            ("user", "那上海呢"),
        ])


class TestContextLimits(unittest.TestCase):
    def test_token_budget_sliding_window(self):
        """即使消息条数很少，Token 估算超限也应丢弃最旧轮次。"""
        cm = ContextManager(max_turns=99, max_messages=99, max_tokens=100)
        for i in range(3):
            cm.add_user_message(f"问题{i}" + "很长" * 50)
            cm.add_assistant_message(_assistant_text("回答" + "很长" * 50))
        cm.get_messages()
        self.assertEqual(cm.turn_count, 1)
        self.assertGreater(estimate_tokens(cm.messages), 0)
    def test_max_turns_sliding_window(self):
        """超过最大轮次时从头部丢弃最旧的轮次。"""
        cm = ContextManager(max_turns=3, max_messages=99)
        for i in range(1, 5):  # 4 轮，超限
            cm.add_user_message(f"问题{i}")
            cm.add_assistant_message(_assistant_text(f"回答{i}"))
        cm.get_messages()
        self.assertEqual(cm.turn_count, 3)
        self.assertEqual(cm.messages[0]["content"], "问题2")

    def test_pair_boundary_alignment(self):
        """压缩不留下半截工具调用：首条必须是用户文本消息。"""
        cm = ContextManager(max_turns=1, max_messages=99)
        cm.add_user_message("查北京天气")
        cm.add_assistant_message(_assistant_tool_call())
        cm.add_tool_results(_tool_result())
        cm.add_assistant_message(_assistant_text("北京晴"))
        cm.add_user_message("换个话题")  # 第 2 轮，超限
        msgs = cm.get_messages()
        first = msgs[0]
        self.assertEqual(first["role"], "user")
        self.assertIsInstance(first["content"], str)
        # 没有孤立的 tool_result
        for m in msgs:
            if isinstance(m["content"], list):
                self.assertNotIn("tool_result", [b.get("type") for b in m["content"]][:1])

    def test_tool_result_truncation(self):
        """超长工具结果头尾截断并标注省略。"""
        cm = ContextManager(tool_result_max_chars=100)
        cm.add_tool_results(_tool_result(content="A" * 300))
        text = cm.messages[0]["content"][0]["content"]
        self.assertLess(len(text), 300)
        self.assertIn("省略", text)


class TestContextStateAndRollback(unittest.TestCase):
    def test_replace_keeps_shared_session_list(self):
        """压缩替换内容后，Session 持有的列表引用仍然有效。"""
        shared = [{"role": "user", "content": "旧消息"}]
        cm = ContextManager(shared)
        cm.replace([{"role": "user", "content": "新消息"}])
        self.assertIs(cm.messages, shared)
        self.assertEqual(shared[0]["content"], "新消息")

    def test_state_persists_across_sessions_reload(self):
        """持续对话记住之前的状态：持久化后重载，上下文原样恢复。"""
        tmp = Path(tempfile.mkdtemp())
        try:
            sm = SessionManager(sessions_dir=tmp)
            s = sm.create()
            cm = ContextManager(s.history)
            cm.add_user_message("记住我喜欢吃西瓜")
            s.history = cm.messages
            sm.save(s)

            s_back = SessionManager(sessions_dir=tmp).load(s.id)
            self.assertEqual(s_back.history[0]["content"], "记住我喜欢吃西瓜")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_rollback_removes_incomplete_turn(self):
        """回滚丢弃本轮未完成的消息（如半截 tool_use）。"""
        cm = ContextManager()
        cm.add_user_message("原始问题")
        mark = len(cm)
        cm.add_assistant_message(_assistant_tool_call())  # 未配对的 tool_use
        cm.rollback(mark)
        self.assertEqual(len(cm), 1)
        self.assertEqual(cm.messages[0]["content"], "原始问题")


if __name__ == "__main__":
    unittest.main()
