import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .config import (
    COMPACT_AFTER_MESSAGES,
    COMPACT_AFTER_TOKENS,
    COMPACT_PROMPT_PATH,
    MODEL,
    RECENT_MESSAGES,
    client,
    get_model,
)
from .context import estimate_tokens
from .memory import MEMORY
from .storage import to_jsonable


logger = logging.getLogger(__name__)
_DEFAULT_CLIENT = client


@dataclass(frozen=True, slots=True)
class CompactionDraft:
    episode: str
    long_term: str
    user_profile: str

    @classmethod
    def parse(cls, text: str) -> "CompactionDraft | None":
        values = tuple(_extract_tag(text, tag) for tag in ("episode", "updated_memory", "updated_user"))
        return cls(*values) if all(values) else None


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{message.get('role', '?')}: "
        f"{json.dumps(to_jsonable(message.get('content')), ensure_ascii=False)}"
        for message in messages
    )


def _extract_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _split_at_user_turn(history: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """在完整用户轮次边界切分，避免拆散 tool_use/tool_result。"""
    target = max(0, len(history) - RECENT_MESSAGES)

    def is_turn_start(index: int) -> bool:
        message = history[index]
        return message.get("role") == "user" and isinstance(message.get("content"), str)

    split_at = next((index for index in range(target, len(history)) if is_turn_start(index)), -1)
    if split_at < 0:
        split_at = next((index for index in range(target - 1, -1, -1) if is_turn_start(index)), 0)
    return history[:split_at], history[split_at:]


def _model_text(message: Any) -> str:
    for block in getattr(message, "content", ()):
        block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if block_type == "text":
            return block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
    return ""


def _commit(draft: CompactionDraft) -> bool:
    commit = getattr(MEMORY, "commit_compaction", None)
    if callable(commit):
        return bool(commit(draft.long_term, draft.user_profile, draft.episode))
    return all((
        MEMORY.write_memory(draft.long_term),
        MEMORY.write_user(draft.user_profile),
        MEMORY.append_episode(draft.episode),
    ))


def compact_history(history: list[dict]) -> list[dict]:
    """达到阈值时把旧轮次沉淀为记忆；任何失败都保留完整历史。"""
    if len(history) <= COMPACT_AFTER_MESSAGES and estimate_tokens(history) <= COMPACT_AFTER_TOKENS:
        return history

    old_messages, recent_messages = _split_at_user_turn(history)
    if not old_messages:
        return history

    try:
        template = COMPACT_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = template.format(
            old_conversation=_messages_to_text(old_messages),
            current_memory=MEMORY.read_memory(),
            current_user=MEMORY.read_user(),
            today_episode=MEMORY.read_today_episode(),
            now_hhmm=datetime.now().astimezone().strftime("%H:%M"),
        )
        model_name = MODEL or (get_model() if client is _DEFAULT_CLIENT else "test-model")
        message = client.messages.create(
            model=model_name,
            max_tokens=3_000,
            system="你是记忆整理员。请严格按要求输出 XML，不要输出额外解释。",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.warning("记忆压缩失败，保留完整 history：%s", exc)
        return history

    draft = CompactionDraft.parse(_model_text(message))
    if draft is None:
        logger.warning("记忆压缩输出不完整，保留完整 history")
        return history
    if not _commit(draft):
        logger.warning("记忆压缩提交失败，保留完整 history")
        return history

    logger.info("记忆已压缩：old=%s recent=%s", len(old_messages), len(recent_messages))
    return recent_messages
