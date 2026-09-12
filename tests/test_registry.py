"""工具声明、Schema、参数分发和包导入契约测试。"""
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ..core import config as config_module
from ..tools import TOOLS, execute_tool
from ..tools.base import BaseTool
from ..tools import registry as registry_module
from ..tools.registry import REGISTERED_TOOLS


class TestToolContracts(unittest.TestCase):
    def test_all_tools_are_basetool_instances(self):
        for tool in REGISTERED_TOOLS:
            self.assertIsInstance(tool, BaseTool)

    def test_every_tool_has_complete_metadata(self):
        """每个工具必须有非空的名称、描述、参数 Schema。"""
        for tool in REGISTERED_TOOLS:
            with self.subTest(tool=tool.name):
                self.assertTrue(tool.name, "工具名不能为空")
                # description 是模型选择工具的唯一依据，必须是有意义的长度
                self.assertGreaterEqual(len(tool.description), 10,
                                        "description 过短，模型无法据此做出调用决策")
                self.assertEqual(tool.input_schema.get("type"), "object")
                self.assertIn("properties", tool.input_schema)
                self.assertIn("required", tool.input_schema)

    def test_required_params_exist_in_properties(self):
        """required 中的参数必须在 properties 中有定义，否则 Schema 自相矛盾。"""
        for tool in REGISTERED_TOOLS:
            with self.subTest(tool=tool.name):
                props = set(tool.input_schema["properties"].keys())
                for req in tool.input_schema["required"]:
                    self.assertIn(req, props)

    def test_tools_list_matches_registered(self):
        """发给 LLM 的工具必须与注册表完全一致。"""
        registered_names = {t.name for t in REGISTERED_TOOLS}
        self.assertEqual({t["name"] for t in TOOLS}, registered_names)
        for schema in TOOLS:
            self.assertEqual(set(schema.keys()), {"name", "description", "input_schema"})

    def test_registry_covers_all_tools(self):
        """注册集合保持不可变且工具名称不能重复。"""
        names = [tool.name for tool in REGISTERED_TOOLS]
        self.assertIsInstance(REGISTERED_TOOLS, tuple)
        self.assertEqual(len(names), len(set(names)))

    def test_unknown_tool_returns_error(self):
        result = execute_tool(SimpleNamespace(name="no_such_tool", input={}))
        self.assertIn("Unknown tool", result)

    def test_wrong_parameter_type_is_rejected(self):
        result = execute_tool(SimpleNamespace(
            name="web_search", input={"query": "test", "max_results": "many"}
        ))
        self.assertIn("类型错误", result)

    def test_unknown_parameter_is_rejected(self):
        result = execute_tool(SimpleNamespace(
            name="calculator", input={"expression": "1+1", "extra": True}
        ))
        self.assertIn("未定义参数", result)

    def test_new_research_and_workspace_tools_are_exposed(self):
        names = {tool["name"] for tool in TOOLS}
        self.assertTrue({
            "fetch_webpage", "search_workspace", "read_workspace_file"
        }.issubset(names))
        self.assertNotIn("run_command", names)
        self.assertNotIn("weather", names)

    def test_malformed_tool_block_returns_error(self):
        result = execute_tool(SimpleNamespace(input={}))
        self.assertIn("missing tool name", result)

    def test_tools_package_imports_in_fresh_process(self):
        """防止 core 与 tools 的导入顺序重新形成循环依赖。"""
        project_parent = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from SimonAgent.tools import TOOLS, execute_tool; "
                "assert len(TOOLS) == 6; assert callable(execute_tool)",
            ],
            cwd=project_parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_exported_schema_is_a_defensive_copy(self):
        tool = REGISTERED_TOOLS[0]
        exported = tool.to_schema()
        exported["input_schema"]["properties"].clear()
        self.assertTrue(tool.input_schema["properties"])

    def test_webpage_result_respects_global_tool_limit(self):
        with patch.object(config_module, "TOOL_RESULT_MAX_CHARS", 3000), \
             patch.object(registry_module, "fetch_webpage", return_value="ok") as mocked:
            result = execute_tool(SimpleNamespace(
                name="fetch_webpage",
                input={"url": "https://example.com", "max_chars": 9000},
            ))
        self.assertEqual(result, "ok")
        mocked.assert_called_once_with("https://example.com", 3000)

    def test_basetool_requires_complete_definition(self):
        with self.assertRaises(TypeError):
            BaseTool()

    def test_tool_definition_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            REGISTERED_TOOLS[0].name = "changed"


if __name__ == "__main__":
    unittest.main()
