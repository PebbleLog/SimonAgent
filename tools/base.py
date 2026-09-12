"""工具定义对象。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re
from typing import Any, Callable

ToolHandler = Callable[[dict[str, Any]], str]
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class BaseTool:
    """一个不可变的工具定义：元数据、参数 Schema 和执行函数。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        """
        实例创建后自动执行，做运行时校验和清理。
        """
        name = self.name.strip()
        description = self.description.strip()
        schema = deepcopy(self.input_schema)

        if not _TOOL_NAME_PATTERN.fullmatch(name):
            raise ValueError("工具名必须是小写 snake_case，且不超过 64 个字符")
        if len(description) < 10:
            raise ValueError("工具描述不能少于 10 个字符")
        if not callable(self.handler):
            raise TypeError("handler 必须可调用")
        if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
            raise ValueError("input_schema 必须描述包含 properties 的 JSON object")
        required = schema.get("required", [])
        if not isinstance(required, list) or not set(required) <= set(schema["properties"]):
            raise ValueError("required 中存在未定义参数")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "input_schema", schema)

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.handler(tool_input)

    def to_schema(self) -> dict[str, Any]:
        """返回独立 Schema，避免模型 SDK 修改原始工具定义。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": deepcopy(self.input_schema),
        }
