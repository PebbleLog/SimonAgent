"""SimonAgent 核心层的稳定公共接口。"""

from .compactor import compact_history
from .config import AgentSettings, SETTINGS
from .context import ContextManager
from .loop import agent_turn, build_system_prompt
from .memory import MEMORY, MemorySnapshot, MemoryStore
from .runner import AgentRunner
from .session import Session, SessionManager
from .skill import SKILL_LOADER, SkillDefinition, SkillLoader

__all__ = (
    "AgentRunner",
    "AgentSettings",
    "SETTINGS",
    "ContextManager",
    "Session",
    "SessionManager",
    "MemoryStore",
    "MemorySnapshot",
    "MEMORY",
    "SkillLoader",
    "SkillDefinition",
    "SKILL_LOADER",
    "compact_history",
    "build_system_prompt",
    "agent_turn",
)
