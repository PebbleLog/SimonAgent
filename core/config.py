import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from .exceptions import ConfigError


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = PACKAGE_ROOT / "Skill"
MEMORY_DIR = PACKAGE_ROOT / "memory"
TEMPLATES_DIR = PACKAGE_ROOT / "templates"
SESSIONS_DIR = PACKAGE_ROOT / "sessions"
COMPACT_PROMPT_PATH = TEMPLATES_DIR / "agent" / "compact_prompt.md"
ENV_PATH = PACKAGE_ROOT / ".env"

_PLACEHOLDER_PREFIXES = ("your_", "replace_", "xxx")


def _load_environment(*, required: bool = False) -> None:
    """加载本地 .env；部署环境也可以直接注入系统环境变量。"""
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError as exc:
        if required:
            raise ConfigError("缺少 python-dotenv，请先安装项目依赖") from exc
        return
    if ENV_PATH.is_file():
        load_dotenv(ENV_PATH, override=False)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value.lower().startswith(_PLACEHOLDER_PREFIXES):
        raise ConfigError(f"缺少有效的环境变量 {name}，请在 {ENV_PATH} 或运行环境中配置")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数，当前值为 {raw!r}") from exc
    if value < 1:
        raise ConfigError(f"{name} 必须大于 0，当前值为 {value}")
    return value


def _template_path(filename: str) -> Path:
    candidate = (TEMPLATES_DIR / filename).resolve()
    if not candidate.is_relative_to(TEMPLATES_DIR.resolve()):
        raise ConfigError("AGENT_SOUL_FILE 必须位于 templates 目录内")
    return candidate


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """启动时确定的运行参数，集中校验后供核心模块只读使用。"""

    max_turns: int
    context_max_messages: int
    context_max_tokens: int
    tool_result_max_chars: int
    tool_max_workers: int
    compact_after_messages: int
    compact_after_tokens: int
    recent_messages: int
    max_steps: int
    max_output_tokens: int
    soul_path: Path

    @classmethod
    def from_env(cls) -> "AgentSettings":
        return cls(
            max_turns=_positive_int("AGENT_MAX_TURNS", 20),
            context_max_messages=_positive_int("AGENT_CONTEXT_MAX_MESSAGES", 40),
            context_max_tokens=_positive_int("AGENT_CONTEXT_MAX_TOKENS", 12_000),
            tool_result_max_chars=_positive_int("AGENT_TOOL_RESULT_MAX_CHARS", 3_000),
            tool_max_workers=_positive_int("AGENT_TOOL_MAX_WORKERS", 4),
            compact_after_messages=_positive_int("AGENT_MEMORY_COMPACT_AFTER", 18),
            compact_after_tokens=_positive_int("AGENT_MEMORY_COMPACT_AFTER_TOKENS", 8_000),
            recent_messages=_positive_int("AGENT_RECENT_MESSAGES", 10),
            max_steps=_positive_int("AGENT_MAX_STEPS", 8),
            max_output_tokens=_positive_int("AGENT_MAX_OUTPUT_TOKENS", 1_000),
            soul_path=_template_path(os.environ.get("AGENT_SOUL_FILE", "").strip() or "SOUL.md"),
        )


def create_client() -> Any:
    """按需创建 Anthropic 兼容客户端，不在模块导入时建立连接。"""
    _load_environment()
    api_key = _require_env("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None
    if base_url and base_url.lower().startswith(_PLACEHOLDER_PREFIXES):
        base_url = None
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        raise ConfigError("缺少 anthropic，请先安装项目依赖") from exc
    try:
        return anthropic.Anthropic(api_key=api_key, base_url=base_url)
    except Exception as exc:
        raise ConfigError(f"Anthropic 客户端创建失败：{exc}") from exc


def get_model() -> str:
    _load_environment()
    return _require_env("ANTHROPIC_MODEL")


class LazyAnthropicClient:
    """线程安全的惰性客户端代理，测试导入时不依赖真实密钥。"""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._lock = Lock()

    def _get(self) -> Any:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = create_client()
        return self._client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


_load_environment()
SETTINGS = AgentSettings.from_env()
client = LazyAnthropicClient()
MODEL = os.environ.get("ANTHROPIC_MODEL", "").strip()

# 保留简短常量别名，让业务模块和已有扩展无需感知设置对象的内部结构。
MAX_TURNS = SETTINGS.max_turns
CONTEXT_MAX_MESSAGES = SETTINGS.context_max_messages
CONTEXT_MAX_TOKENS = SETTINGS.context_max_tokens
TOOL_RESULT_MAX_CHARS = SETTINGS.tool_result_max_chars
TOOL_MAX_WORKERS = SETTINGS.tool_max_workers
COMPACT_AFTER_MESSAGES = SETTINGS.compact_after_messages
COMPACT_AFTER_TOKENS = SETTINGS.compact_after_tokens
RECENT_MESSAGES = SETTINGS.recent_messages
AGENT_MAX_STEPS = SETTINGS.max_steps
AGENT_MAX_OUTPUT_TOKENS = SETTINGS.max_output_tokens
SOUL_PATH = SETTINGS.soul_path
