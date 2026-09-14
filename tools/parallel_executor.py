"""并行工具执行器：线程池并行调度多个工具调用，结果顺序与输入一致。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .registry import execute_tool


def _check_max_workers(max_workers: int) -> int:
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers 必须是大于 0 的整数")
    return max_workers


def _default_max_workers() -> int:
    # 运行时读取核心配置，避免模块初始化阶段产生 core ↔ tools 循环导入。
    from ..core.config import TOOL_MAX_WORKERS

    return TOOL_MAX_WORKERS


def execute_tools_parallel(blocks: list[Any], *, max_workers: int | None = None) -> list[str]:
    """并行执行多个工具调用，结果顺序与输入严格对应；单个任务直接串行执行。"""
    workers = _check_max_workers(_default_max_workers() if max_workers is None else max_workers)
    blocks = list(blocks)
    if len(blocks) <= 1:
        return [execute_tool(block) for block in blocks]

    print(f"[并行执行]: {len(blocks)} 个工具任务，线程数 {min(workers, len(blocks))}")
    with ThreadPoolExecutor(max_workers=min(workers, len(blocks))) as pool:
        return list(pool.map(execute_tool, blocks))


# 预留接口：当前主循环是同步的，尚未使用；后续主循环异步化时，用
# `await async_execute_tools(...)` 替换 `execute_tools_parallel(...)`，
# 即可在工具并行执行的同时让出事件循环处理其他任务。
async def async_execute_tools(blocks: list[Any], *, max_workers: int | None = None) -> list[str]:
    """异步薄封装：在线程池中并行执行，供异步调用方 await 使用。"""
    workers = _check_max_workers(_default_max_workers() if max_workers is None else max_workers)
    blocks = list(blocks)
    if len(blocks) <= 1:
        return [execute_tool(block) for block in blocks]
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=min(workers, len(blocks))) as pool:
        tasks = [loop.run_in_executor(pool, execute_tool, block) for block in blocks]
        return list(await asyncio.gather(*tasks))
