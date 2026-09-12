import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SESSIONS_DIR
from .exceptions import SessionNotFoundError
from .storage import atomic_write_text, to_jsonable


_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(slots=True)
class Session:
    """一个可持久化的独立会话。"""

    id: str
    created_at: str
    history: list[dict[str, Any]] = field(default_factory=list)

    def preview(self, max_chars: int = 20) -> str:
        """返回首条用户文本的单行预览。"""
        for message in self.history:
            content = message.get("content")
            if message.get("role") == "user" and isinstance(content, str):
                text = " ".join(content.split())
                return text[:max_chars] + ("..." if len(text) > max_chars else "")
        return "(空会话)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "history": to_jsonable(self.history),
        }

    @classmethod
    def from_dict(cls, data: object) -> "Session":
        """从磁盘数据恢复会话，并拒绝结构损坏的数据。"""
        if not isinstance(data, dict):
            raise ValueError("会话数据必须是 JSON 对象")

        session_id = data.get("id")
        created_at = data.get("created_at", "")
        history = data.get("history", [])
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("会话 id 缺失或格式错误")
        if not isinstance(created_at, str):
            raise ValueError("会话创建时间格式错误")
        if not isinstance(history, list) or not all(isinstance(item, dict) for item in history):
            raise ValueError("会话历史必须是消息对象列表")

        return cls(id=session_id, created_at=created_at, history=list(history))


class SessionManager:
    """创建、原子保存、加载和列举本地 JSON 会话。"""

    def __init__(self, sessions_dir: Path = SESSIONS_DIR):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(session_id: str) -> str:
        if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise SessionNotFoundError("会话 id 格式不合法")
        return session_id

    def _path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{self._validate_id(session_id)}.json"

    def create(self) -> Session:
        """创建尚未落盘的新会话。"""
        now = datetime.now(timezone.utc)
        session_id = f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        return Session(id=session_id, created_at=now.isoformat(timespec="seconds"))

    def save(self, session: Session) -> None:
        """以 UTF-8 JSON 原子保存完整会话。"""
        if not isinstance(session, Session):
            raise TypeError("session 必须是 Session 实例")
        path = self._path(session.id)
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        atomic_write_text(path, payload + "\n")

    def load(self, session_id: str) -> Session:
        """按完整 ID 或唯一前缀加载会话。"""
        resolved_id = self._resolve_id(session_id)
        path = self._path(resolved_id)
        try:
            session = Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if session.id != resolved_id:
                raise ValueError("文件名与会话 id 不一致")
            return session
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise SessionNotFoundError(f"会话文件损坏或不可读：{path.name}（{exc}）") from exc

    def list(self) -> list[Session]:
        """列出有效会话，按创建时间和 ID 稳定排序。"""
        sessions: list[Session] = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                session = Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if self._validate_id(path.stem) != session.id:
                    continue
                sessions.append(session)
            except (OSError, json.JSONDecodeError, ValueError, SessionNotFoundError):
                continue
        return sorted(sessions, key=lambda item: (item.created_at, item.id))

    def _resolve_id(self, session_id: str) -> str:
        """把合法的完整 ID 或唯一前缀解析为完整 ID。"""
        session_id = self._validate_id(session_id)
        if self._path(session_id).is_file():
            return session_id

        matches = [session.id for session in self.list() if session.id.startswith(session_id)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise SessionNotFoundError(
                f"会话 id 前缀 '{session_id}' 匹配到 {len(matches)} 个会话，请输入更长的前缀"
            )
        raise SessionNotFoundError(f"未找到会话 '{session_id}'，可用 /list 查看所有会话")
