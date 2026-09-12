"""内置工具的正常路径、错误降级与安全边界测试。"""

import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from ..tools.builtin import (
    calculate,
    fetch_webpage,
    read_workspace_file,
    search_workspace,
    web_search,
)
from ..tools.builtin import search as search_module
from ..tools.builtin import webpage as webpage_module
from ..tools.builtin.search import TavilyConfigError


class TestCalculator(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(calculate("(3+5)*2"), "(3+5)*2 = 16")
        self.assertEqual(calculate("2**10"), "2**10 = 1024")
        self.assertEqual(calculate("10/4"), "10/4 = 2.5")

    def test_safe_functions_and_constants(self):
        self.assertEqual(calculate("sqrt(81) + round(pi, 2)"),
                         "sqrt(81) + round(pi, 2) = 12.14")
        self.assertEqual(calculate("max(3, 8, 5)"), "max(3, 8, 5) = 8")

    def test_division_by_zero_returns_error(self):
        self.assertTrue(calculate("10/0").startswith("Error"))

    def test_injection_rejected(self):
        result = calculate('__import__("os")')
        self.assertTrue(result.startswith("Error"))

    def test_large_power_rejected(self):
        self.assertIn("幂指数", calculate("2**1000"))


_FAKE_TAVILY = {
    "answer": "示例回答",
    "results": [
        {"title": "示例结果", "url": "https://example.com", "content": "摘要内容"},
    ],
}


class TestWebSearch(unittest.TestCase):
    def test_success_format(self):
        with patch.object(search_module, "tavily_request", return_value=_FAKE_TAVILY):
            result = web_search("AI 新闻", max_results=1)
        self.assertIn("搜索关键词: AI 新闻", result)
        self.assertIn("示例结果", result)
        self.assertIn("https://example.com", result)

    def test_api_failure_returns_error(self):
        with patch.object(search_module, "tavily_request",
                          side_effect=TavilyConfigError("未配置")):
            result = web_search("test")
        self.assertTrue(result.startswith("Error"))

    def test_empty_query(self):
        self.assertTrue(web_search("  ").startswith("Error"))

    def test_invalid_results_shape(self):
        with patch.object(search_module, "tavily_request", return_value={"results": {}}):
            result = web_search("test")
        self.assertIn("返回格式错误", result)


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "text/html"):
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = f"{content_type}; charset=utf-8"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return "https://example.com/article"

    def read(self, size=-1):
        return self._body[:size] if size >= 0 else self._body


class TestFetchWebpage(unittest.TestCase):
    def test_extracts_visible_html_text(self):
        body = (b"<html><head><title>Example</title><style>hidden</style></head>"
                b"<body><h1>Hello</h1><script>secret</script><p>Agent article</p></body></html>")
        response = _FakeResponse(body)
        with patch.object(webpage_module, "_validate_public_url", side_effect=lambda url: url), \
             patch.object(webpage_module, "_open_url", return_value=response):
            result = fetch_webpage("https://example.com/article", 500)
        self.assertIn("网页标题: Example", result)
        self.assertIn("Hello", result)
        self.assertIn("Agent article", result)
        self.assertNotIn("secret", result)
        self.assertNotIn("hidden", result)
        self.assertEqual(result.count("Example"), 1)

    def test_localhost_is_rejected(self):
        result = fetch_webpage("http://localhost/admin")
        self.assertIn("不允许访问", result)

    def test_unsupported_content_type(self):
        response = _FakeResponse(b"binary", "application/octet-stream")
        with patch.object(webpage_module, "_validate_public_url", side_effect=lambda url: url), \
             patch.object(webpage_module, "_open_url", return_value=response):
            result = fetch_webpage("https://example.com/file")
        self.assertIn("不支持", result)


class TestWorkspaceTools(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "core").mkdir()
        (self.root / "core" / "runner.py").write_text(
            "class AgentRunner:\n    pass\n", encoding="utf-8")
        (self.root / "README.md").write_text("AgentRunner 使用说明\n", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=abc\n", encoding="utf-8")
        (self.root / "memory").mkdir()
        (self.root / "memory" / "MEMORY.md").write_text("AgentRunner secret\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_search_returns_file_and_line(self):
        result = search_workspace("AgentRunner", root=self.root)
        self.assertIn("core/runner.py:1", result)
        self.assertIn("README.md:1", result)
        self.assertNotIn("MEMORY.md", result)

    def test_read_file_with_line_range(self):
        result = read_workspace_file("core/runner.py", 2, 1, root=self.root)
        self.assertIn("第 2-2 行", result)
        self.assertIn("2 |     pass", result)

    def test_path_traversal_is_rejected(self):
        result = read_workspace_file("../outside.py", root=self.root)
        self.assertTrue(result.startswith("Error"))

    def test_sensitive_file_is_rejected(self):
        result = read_workspace_file(".env", root=self.root)
        self.assertTrue(result.startswith("Error"))


if __name__ == "__main__":
    unittest.main()
