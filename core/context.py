import json
import logging
from typing import Any

from .config import (
    CONTEXT_MAX_MESSAGES,
    CONTEXT_MAX_TOKENS,
    MAX_TURNS,
    TOOL_RESULT_MAX_CHARS,
)


logger = logging.getLogger(__name__)
Message = dict[str, Any]


def estimate_tokens(value: Any) -> int:
    """用 UTF-8 体积估算 Token，仅用于本地提前裁剪。"""
    encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    return max(1, (len(encoded) + 3) // 4)


def _is_turn_start(message: Message) -> bool:
    return message.get("role") == "user" and isinstance(message.get("content"), str)


def _truncate_tool_results(messages: list[Message], max_chars: int) -> None:
    """
    截断过长的工具返回结果，保留头尾各一半，中间用省略提示替换。
    """
    for message in messages:
        blocks = message.get("content")
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            text = block.get("content")
            if not isinstance(text, str) or len(text) <= max_chars:
                continue
            head = (max_chars + 1) // 2
            tail = max_chars // 2
            omitted = len(text) - max_chars
            tail_text = text[-tail:] if tail else ""
            block["content"] = f"{text[:head]}\n...[中间省略 {omitted} 字符]...\n{tail_text}"


class ContextManager:
    """维护单个会话的消息窗口，并保证工具协议边界完整。"""

    def __init__(
        self,
        messages: list[Message] | None = None,
        max_turns: int = MAX_TURNS,
        max_messages: int = CONTEXT_MAX_MESSAGES,
        tool_result_max_chars: int = TOOL_RESULT_MAX_CHARS,
        max_tokens: int = CONTEXT_MAX_TOKENS,
    ):
        limits = (max_turns, max_messages, tool_result_max_chars, max_tokens)
        if any(value < 1 for value in limits):
            raise ValueError("上下文限制必须全部大于 0")
        self.messages = messages if messages is not None else []
        self.max_turns = max_turns
        self.max_messages = max_messages
        self.tool_result_max_chars = tool_result_max_chars
        self.max_tokens = max_tokens

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant_message(self, content: Any) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, tool_results: list[dict[str, Any]]) -> None:
        message: Message = {"role": "user", "content": tool_results}
        _truncate_tool_results([message], self.tool_result_max_chars)
        self.messages.append(message)

    @property
    def turn_count(self) -> int:
        return sum(_is_turn_start(message) for message in self.messages)

    def is_over_limit(self) -> bool:
        return (
            self.turn_count > self.max_turns
            or len(self.messages) > self.max_messages
            or estimate_tokens(self.messages) > self.max_tokens
        )

    def get_messages(self) -> list[Message]:
        self.apply_basic_compression()
        return self.messages

    def apply_basic_compression(self) -> None:
        """逐轮移除最旧消息，始终从下一条用户文本边界开始保留。"""
        _truncate_tool_results(self.messages, self.tool_result_max_chars)
        dropped = 0
        while self.is_over_limit() and self.turn_count > 1:
            next_turn = next(
                (index for index, message in enumerate(self.messages[1:], 1) if _is_turn_start(message)),
                len(self.messages),
            )
            del self.messages[:next_turn]
            dropped += next_turn
        if dropped:
            logger.info(
                "上下文裁剪：丢弃 %s 条，保留 %s 条/%s 轮，约 %s tokens",
                dropped,
                len(self.messages),
                self.turn_count,
                estimate_tokens(self.messages),
            )

    def replace(self, messages: list[Message]) -> None:
        """原位替换内容，保持 Session 与 Context 共享同一列表引用。"""
        self.messages[:] = messages

    def rollback(self, mark: int) -> None:
        if not 0 <= mark <= len(self.messages):
            raise ValueError("回滚位置超出上下文范围")
        del self.messages[mark:]

    def __len__(self) -> int:
        return len(self.messages)
