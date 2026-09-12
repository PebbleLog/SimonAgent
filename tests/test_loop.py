"""Agent Loop 的直接回复、工具回填与执行上限测试。"""
import unittest
from unittest.mock import patch

from ..core import ContextManager
from ..core import loop as loop_module
from ..core.loop import agent_turn
from .helpers import (
    FakeClient, MemoryStub, fake_message, text_block, tool_use_block,
)


class TestAgentTurn(unittest.TestCase):
    def _run(self, responses):
        ctx = ContextManager()
        ctx.add_user_message("测试输入")
        with patch.object(loop_module, "client", FakeClient(responses)), \
             patch.object(loop_module, "MEMORY", MemoryStub()):
            agent_turn(ctx)
        return ctx

    def test_direct_reply_end_turn(self):
        """模型直接回复（end_turn）：一轮结束，user+assistant 两条消息。"""
        ctx = self._run([fake_message([text_block("直接回复")], "end_turn")])
        self.assertEqual(len(ctx.messages), 2)
        self.assertEqual(ctx.messages[-1]["role"], "assistant")

    def test_tool_use_then_reply(self):
        """模型先调工具（tool_use）再给最终回复：loop 执行两轮模型调用，
        且上下文中有完整的 tool_use/tool_result 配对。"""
        responses = [
            fake_message([tool_use_block("calculator", {"expression": "1+2"})], "tool_use"),
            fake_message([text_block("结果是3")], "end_turn"),
        ]
        ctx = self._run(responses)
        # user → assistant(tool_use) → user(tool_result) → assistant(text)
        self.assertEqual(len(ctx.messages), 4)
        tool_result_msg = ctx.messages[2]
        self.assertEqual(tool_result_msg["role"], "user")
        self.assertEqual(tool_result_msg["content"][0]["type"], "tool_result")
        # calculator 真实执行了：1+2 = 3
        self.assertIn("1+2 = 3", tool_result_msg["content"][0]["content"])

    def test_tool_pair_integrity(self):
        """工具调用后，tool_result 的 tool_use_id 必须与 tool_use 的 id 一致（API 配对约束）。"""
        responses = [
            fake_message([tool_use_block("calculator", {"expression": "2*3"}, "abc123")], "tool_use"),
            fake_message([text_block("ok")], "end_turn"),
        ]
        ctx = self._run(responses)
        tool_use = ctx.messages[1]["content"][0]
        tool_result = ctx.messages[2]["content"][0]
        self.assertEqual(tool_result["tool_use_id"], tool_use.id)

    def test_step_limit_stops_repeated_tool_calls(self):
        """模型持续调用工具时，达到上限后以合法 assistant 消息结束。"""
        ctx = ContextManager()
        ctx.add_user_message("一直计算")
        repeating = fake_message(
            [tool_use_block("calculator", {"expression": "1+1"})], "tool_use"
        )
        with patch.object(loop_module, "client", FakeClient([repeating])), \
             patch.object(loop_module, "MEMORY", MemoryStub()):
            agent_turn(ctx, max_steps=2)
        self.assertEqual(ctx.messages[-1]["role"], "assistant")
        self.assertIn("最大执行步数", ctx.messages[-1]["content"][0]["text"])

    def test_system_prompt_explains_tool_chains(self):
        """系统提示词应指导模型正确组合新增工具，而不是只依赖 Schema 猜测。"""
        with patch.object(loop_module, "MEMORY", MemoryStub()):
            prompt = loop_module.build_system_prompt()
        self.assertIn("web_search", prompt)
        self.assertIn("fetch_webpage", prompt)
        self.assertIn("search_workspace", prompt)
        self.assertIn("read_workspace_file", prompt)
        self.assertIn("不要编造成功结果", prompt)


if __name__ == "__main__":
    unittest.main()
