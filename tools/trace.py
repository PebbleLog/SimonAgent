"""
负责记录 Agent 每次调用工具的历史信息，采用内存环形缓冲 + JSONL 文件持久化的双写策略。
"""
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

_DEFAULT_TRACE_LOG = Path(__file__).resolve().parents[1] / "logs" / "tool_trace.jsonl"

# 单条结果预览的最大字符数（完整结果在会话上下文中，日志只留预览）
_RESULT_PREVIEW_CHARS = 200
_SENSITIVE_KEY_PARTS = ("key", "token", "password", "secret", "authorization", "cookie")


def _redact(value: Any) -> Any:
    """按常见敏感字段名递归脱敏，避免密钥直接进入工具日志。"""
    if isinstance(value, dict):
        return {
            key: ("***" if any(part in str(key).casefold() for part in _SENSITIVE_KEY_PARTS)
                  else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class ToolTracer:
    """工具调用记录器：内存环形缓冲 + JSONL 持久化。"""

    def __init__(self, log_path: Path | None = None, memory_limit: int = 50):
        if isinstance(memory_limit, bool) or not isinstance(memory_limit, int) or memory_limit < 1:
            raise ValueError("memory_limit 必须是大于 0 的整数")
        self.log_path = Path(log_path) if log_path is not None else _DEFAULT_TRACE_LOG
        self.memory_limit = memory_limit
        self._entries: deque[dict[str, Any]] = deque(maxlen=memory_limit)
        self._lock = RLock()

    @property
    def entries(self) -> list[dict[str, Any]]:
        """返回内存记录快照，避免调用方直接修改内部环形缓冲。"""
        with self._lock:
            return list(self._entries)

    def record(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        result: str,
        duration_ms: float,
    ) -> dict[str, Any]:
        """记录一次工具调用，返回日志条目。"""
        result = str(result)
        preview = result[:_RESULT_PREVIEW_CHARS].replace("\r", "\\r").replace("\n", "\\n")
        if len(result) > _RESULT_PREVIEW_CHARS:
            preview += "..."
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "tool": str(tool_name),
            "input": _redact(tool_input),
            "ok": not result.lstrip().startswith("Error:"),
            "duration_ms": round(max(0.0, float(duration_ms)), 1),
            "result_chars": len(result),
            "result_preview": preview,
        }

        with self._lock:
            self._entries.append(entry)
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            except OSError:
                pass  # 日志写入失败不影响工具主流程

        return entry

    def recent(self, n: int = 10) -> list[dict[str, Any]]:
        """返回最近 n 条调用记录（新的在后）。"""
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            return []
        with self._lock:
            return list(self._entries)[-n:]

    @staticmethod
    def format_entry(entry: dict[str, Any]) -> str:
        """把日志条目格式化为单行文本，供 /trace 展示。"""
        status = "OK " if entry["ok"] else "ERR"
        args = json.dumps(entry["input"], ensure_ascii=False, default=str)
        if len(args) > 40:
            args = args[:40] + "..."
        return (f"[{entry['ts']}] {status} {entry['tool']}({args}) "
                f"-> {entry['result_chars']} chars, {entry['duration_ms']} ms")


# 全局 trace 单例（registry.execute_tool 与 runner 的 /trace 命令共用）
TRACER = ToolTracer()
