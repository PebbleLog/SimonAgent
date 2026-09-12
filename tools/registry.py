"""工具声明、参数校验和统一执行入口。"""

from __future__ import annotations

import time
from types import MappingProxyType
from typing import Any

from .base import BaseTool
from .builtin import (
    calculate,
    fetch_webpage,
    read_workspace_file,
    search_workspace,
    web_search,
)
from .trace import TRACER


def _string(description: str, *, max_length: int) -> dict[str, Any]:
    return {
        "type": "string",
        "description": description,
        "minLength": 1,
        "maxLength": max_length,
    }


def _integer(description: str, minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type": "integer",
        "description": description,
        "minimum": minimum,
        "maximum": maximum,
    }


def _schema(properties: dict[str, Any], *required: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


# 每个 handler 只做参数解包和调用，异常统一由 execute_tool 处理。
def _load_skill(tool_input: dict[str, Any]) -> str:
    from ..core.skill import SKILL_LOADER

    skill_name = tool_input["skill_name"]
    print(f"[加载技能]: {skill_name}")
    return SKILL_LOADER.get_content(skill_name)


def _calculate(tool_input: dict[str, Any]) -> str:
    expression = tool_input["expression"]
    print(f"[计算]: {expression}")
    return calculate(expression)


def _web_search(tool_input: dict[str, Any]) -> str:
    query = tool_input["query"]
    print(f"[搜索]: {query}")
    return web_search(query, tool_input.get("max_results", 5))


def _fetch_webpage(tool_input: dict[str, Any]) -> str:
    # 运行时读取核心配置，避免模块初始化阶段产生 core ↔ tools 循环导入。
    from ..core.config import TOOL_RESULT_MAX_CHARS

    url = tool_input["url"]
    requested_chars = tool_input.get("max_chars", TOOL_RESULT_MAX_CHARS)
    print(f"[读取网页]: {url}")
    return fetch_webpage(url, min(requested_chars, TOOL_RESULT_MAX_CHARS))


def _search_workspace(tool_input: dict[str, Any]) -> str:
    query = tool_input["query"]
    print(f"[检索项目]: {query}")
    return search_workspace(query, tool_input.get("max_results", 10))


def _read_workspace_file(tool_input: dict[str, Any]) -> str:
    path = tool_input["path"]
    print(f"[读取项目文件]: {path}")
    return read_workspace_file(
        path,
        tool_input.get("start_line", 1),
        tool_input.get("max_lines", 120),
    )


# 声明式工具表：新增工具只需增加一个 BaseTool，无需再编写包装子类。
REGISTERED_TOOLS: tuple[BaseTool, ...] = (
    BaseTool(
        name="load_skill",
        description="加载指定技能的详细知识内容，在回答相关专业问题前调用",
        input_schema=_schema({
            "skill_name": _string("系统提示中列出的技能名称", max_length=100),
        }, "skill_name"),
        handler=_load_skill,
    ),
    BaseTool(
        name="calculator",
        description="安全计算数学表达式，支持基础运算、常量和常用数学函数",
        input_schema=_schema({
            "expression": _string("数学表达式，如 sqrt(81) + round(pi, 2)", max_length=200),
        }, "expression"),
        handler=_calculate,
    ),
    BaseTool(
        name="web_search",
        description="搜索网络实时信息并返回相关网页的标题、链接和摘要",
        input_schema=_schema({
            "query": _string("具体、完整的搜索关键词", max_length=300),
            "max_results": _integer("最大返回结果数，默认 5", 1, 10),
        }, "query"),
        handler=_web_search,
    ),
    BaseTool(
        name="fetch_webpage",
        description="读取公开网页正文，适合在网络搜索后继续核对具体来源",
        input_schema=_schema({
            "url": _string("完整的公网 HTTP(S) 地址", max_length=2048),
            "max_chars": _integer("期望正文字数，最终受全局工具结果上限约束", 500, 12000),
        }, "url"),
        handler=_fetch_webpage,
    ),
    BaseTool(
        name="search_workspace",
        description="在安全范围内检索项目源码和文档，返回文件路径、行号与片段",
        input_schema=_schema({
            "query": _string("代码符号、配置名或文本关键词", max_length=200),
            "max_results": _integer("最大匹配数，默认 10", 1, 20),
        }, "query"),
        handler=_search_workspace,
    ),
    BaseTool(
        name="read_workspace_file",
        description="按行读取项目内的安全文本文件，通常在项目检索后调用",
        input_schema=_schema({
            "path": _string("项目内相对路径，如 core/loop.py", max_length=500),
            "start_line": _integer("起始行号，默认 1", 1, 1_000_000),
            "max_lines": _integer("最多读取行数，默认 120", 1, 200),
        }, "path"),
        handler=_read_workspace_file,
    ),
)

_tool_names = [tool.name for tool in REGISTERED_TOOLS]
if len(_tool_names) != len(set(_tool_names)):
    raise ValueError("工具名称不能重复")

_TOOLS_BY_NAME = MappingProxyType({tool.name: tool for tool in REGISTERED_TOOLS})
TOOLS = [tool.to_schema() for tool in REGISTERED_TOOLS]

_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _validate_tool_input(tool: BaseTool, tool_input: Any) -> str | None:
    """执行前做轻量 JSON Schema 校验。"""
    if not isinstance(tool_input, dict):
        return "工具参数必须是 JSON object"

    schema = tool.input_schema
    properties = schema["properties"]
    missing = [name for name in schema["required"] if name not in tool_input]
    if missing:
        return f"缺少必需参数: {', '.join(missing)}"

    unknown = sorted(set(tool_input) - set(properties))
    if unknown:
        return f"包含未定义参数: {', '.join(unknown)}"

    for name, value in tool_input.items():
        rule = properties[name]
        expected = _JSON_TYPES.get(rule.get("type"))
        is_boolean_number = isinstance(value, bool) and rule.get("type") in {"integer", "number"}
        if expected and (not isinstance(value, expected) or is_boolean_number):
            return f"参数 {name} 类型错误，应为 {rule['type']}"
        if isinstance(value, str):
            if len(value) < rule.get("minLength", 0):
                return f"参数 {name} 不能为空"
            if len(value) > rule.get("maxLength", float("inf")):
                return f"参数 {name} 过长"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < rule.get("minimum", float("-inf")):
                return f"参数 {name} 不能小于 {rule['minimum']}"
            if value > rule.get("maximum", float("inf")):
                return f"参数 {name} 不能大于 {rule['maximum']}"
    return None


def execute_tool(block: Any) -> str:
    """校验、执行并记录一次工具调用，失败时返回可供模型理解的错误。"""
    start = time.perf_counter()
    tool_name = getattr(block, "name", None)
    tool_input = getattr(block, "input", None)
    tool_input = {} if tool_input is None else tool_input

    if not isinstance(tool_name, str) or not tool_name:
        tool_name = "<missing>"
        result = "Error: Invalid tool call: missing tool name"
    elif (tool := _TOOLS_BY_NAME.get(tool_name)) is None:
        result = f"Error: Unknown tool '{tool_name}'"
    elif validation_error := _validate_tool_input(tool, tool_input):
        result = f"Error: Invalid input for tool '{tool_name}': {validation_error}"
    else:
        try:
            result = tool.run(tool_input)
        except Exception as exc:
            result = f"Error: tool '{tool_name}' 执行失败: {exc}"

    result = result if isinstance(result, str) else str(result)
    trace_input = tool_input if isinstance(tool_input, dict) else {
        "invalid_input_type": type(tool_input).__name__,
    }
    TRACER.record(tool_name, trace_input, result, (time.perf_counter() - start) * 1000)
    return result
