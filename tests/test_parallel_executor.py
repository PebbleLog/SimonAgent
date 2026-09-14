"""并行工具执行器的并行调度、顺序保持与错误降级测试。"""

import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ..tools import async_execute_tools, execute_tools_parallel
from ..tools import parallel_executor as executor_module


def _calc(expression: str) -> SimpleNamespace:
    return SimpleNamespace(name="calculator", input={"expression": expression})


class TestParallelExecution(unittest.TestCase):
    def test_results_keep_input_order(self):
        blocks = [_calc("1+1"), _calc("2*3"), _calc("sqrt(81)")]
        results = execute_tools_parallel(blocks)
        self.assertEqual(results, ["1+1 = 2", "2*3 = 6", "sqrt(81) = 9"])

    def test_single_block_runs_serially(self):
        self.assertEqual(execute_tools_parallel([_calc("1+1")]), ["1+1 = 2"])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(execute_tools_parallel([]), [])

    def test_tool_errors_are_returned_not_raised(self):
        blocks = [_calc("1+1"), SimpleNamespace(name="no_such_tool", input={})]
        results = execute_tools_parallel(blocks)
        self.assertEqual(results[0], "1+1 = 2")
        self.assertIn("Unknown tool", results[1])

    def test_invalid_max_workers_is_rejected(self):
        for bad in (0, -1, True, "4"):
            with self.subTest(max_workers=bad), self.assertRaises(ValueError):
                execute_tools_parallel([_calc("1+1")], max_workers=bad)

    def test_multiple_tasks_actually_run_in_parallel(self):
        """两个耗时任务的并行总时长必须明显小于串行之和。"""

        def slow_execute(_block):
            time.sleep(0.4)
            return "ok"

        blocks = [_calc("1+1"), _calc("2+2")]
        with patch.object(executor_module, "execute_tool", side_effect=slow_execute):
            start = time.perf_counter()
            results = execute_tools_parallel(blocks)
            elapsed = time.perf_counter() - start
        self.assertEqual(results, ["ok", "ok"])
        self.assertLess(elapsed, 0.7, "并行执行两个 0.4s 任务不应接近串行的 0.8s")


class TestAsyncWrapper(unittest.TestCase):
    def test_async_execute_tools_returns_ordered_results(self):
        blocks = [_calc("1+1"), _calc("2*3")]
        results = asyncio.run(async_execute_tools(blocks))
        self.assertEqual(results, ["1+1 = 2", "2*3 = 6"])

    def test_async_wrapper_validates_max_workers(self):
        with self.assertRaises(ValueError):
            asyncio.run(async_execute_tools([_calc("1+1")], max_workers=0))


if __name__ == "__main__":
    unittest.main()
