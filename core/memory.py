import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock

from .config import MEMORY_DIR, TEMPLATES_DIR
from .storage import atomic_write_text, to_jsonable


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """一次提示词组装所需的只读记忆快照。"""

    long_term: str = ""
    user_profile: str = ""
    today_episode: str = ""


class MemoryStore:
    """单用户文件记忆；失败时记录告警并保持对话主流程可用。"""

    def __init__(self, memory_dir: Path, templates_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "history.jsonl"
        self.episode_dir = self.memory_dir / "Contextual memory"
        templates_dir = Path(templates_dir)
        self.memory_template_file = templates_dir / "MEMORY.md"
        self.user_template_file = templates_dir / "USER.md"
        self.user_file = self.memory_dir / "USER.md"
        self._lock = RLock()

    @staticmethod
    def _initial_content(template: Path, fallback: str) -> str:
        try:
            return template.read_text(encoding="utf-8") if template.is_file() else fallback
        except (OSError, UnicodeDecodeError):
            return fallback

    def ensure_files(self) -> bool:
        with self._lock:
            try:
                self.memory_dir.mkdir(parents=True, exist_ok=True)
                self.episode_dir.mkdir(parents=True, exist_ok=True)
                if not self.memory_file.exists():
                    content = self._initial_content(
                        self.memory_template_file,
                        "# 长期记忆\n\n暂无需要跨会话保留的信息。\n",
                    )
                    atomic_write_text(self.memory_file, content)
                if not self.user_file.exists():
                    content = self._initial_content(
                        self.user_template_file,
                        "# 用户档案\n\n暂无已确认的用户偏好。\n",
                    )
                    atomic_write_text(self.user_file, content)
                if not self.history_file.exists():
                    self.history_file.touch()
                return True
            except OSError as exc:
                logger.warning("记忆文件初始化失败：%s", exc)
                return False

    def append_history(self, message: dict) -> bool:
        if not self.ensure_files():
            return False
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "role": message.get("role"),
            "content": to_jsonable(message.get("content")),
        }
        with self._lock:
            try:
                with self.history_file.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                return True
            except OSError as exc:
                logger.warning("对话记录写入失败：%s", exc)
                return False

    def _read(self, path: Path, label: str) -> str:
        if not self.ensure_files():
            return ""
        with self._lock:
            try:
                return path.read_text(encoding="utf-8") if path.exists() else ""
            except OSError as exc:
                logger.warning("%s读取失败：%s", label, exc)
                return ""

    def _write(self, path: Path, text: str, label: str) -> bool:
        if not self.ensure_files():
            return False
        with self._lock:
            try:
                atomic_write_text(path, text.strip() + "\n")
                return True
            except OSError as exc:
                logger.warning("%s写入失败：%s", label, exc)
                return False

    def read_memory(self) -> str:
        return self._read(self.memory_file, "长期记忆")

    def write_memory(self, text: str) -> bool:
        return self._write(self.memory_file, text, "长期记忆")

    def read_user(self) -> str:
        return self._read(self.user_file, "用户档案")

    def write_user(self, text: str) -> bool:
        return self._write(self.user_file, text, "用户档案")

    def today_episode_file(self) -> Path:
        return self.episode_dir / f"{datetime.now().astimezone():%Y-%m-%d}.md"

    def read_today_episode(self) -> str:
        return self._read(self.today_episode_file(), "情景记忆")

    def append_episode(self, text: str) -> bool:
        if not self.ensure_files():
            return False
        with self._lock:
            try:
                with self.today_episode_file().open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write("\n" + text.strip() + "\n")
                return True
            except OSError as exc:
                logger.warning("情景记忆写入失败：%s", exc)
                return False

    def commit_compaction(self, long_term: str, user_profile: str, episode: str) -> bool:
        """提交一次完整压缩；失败时尽力恢复提交前的三个文件。
        只有 compactor.py 在记忆压缩完成后调用它，用来一次性安全地写入压缩后的三类记忆。
        """
        if not self.ensure_files():
            return False
        with self._lock:
            episode_file = self.today_episode_file()
            paths = (self.memory_file, self.user_file, episode_file)
            previous: dict[Path, str | None] = {}
            try:
                previous = {path: path.read_text(encoding="utf-8") if path.exists() else None for path in paths}
                episode_text = ((previous[episode_file] or "").rstrip() + "\n\n" + episode.strip() + "\n")
                atomic_write_text(self.memory_file, long_term.strip() + "\n")
                atomic_write_text(self.user_file, user_profile.strip() + "\n")
                atomic_write_text(episode_file, episode_text)
                return True
            except OSError as exc:
                logger.warning("记忆压缩提交失败，正在恢复：%s", exc)
                for path, original in previous.items():
                    try:
                        if original is None:
                            path.unlink(missing_ok=True)
                        else:
                            atomic_write_text(path, original)
                    except OSError as rollback_exc:
                        logger.error("记忆文件恢复失败 %s：%s", path, rollback_exc)
                return False

    def snapshot(self) -> MemorySnapshot:
        """读取同一时刻的提示词记忆，避免调用方了解文件布局。"""
        if not self.ensure_files():
            return MemorySnapshot()
        with self._lock:
            try:
                episode_file = self.today_episode_file()
                return MemorySnapshot(
                    long_term=self.memory_file.read_text(encoding="utf-8"),
                    user_profile=self.user_file.read_text(encoding="utf-8"),
                    today_episode=episode_file.read_text(encoding="utf-8") if episode_file.exists() else "",
                )
            except OSError as exc:
                logger.warning("记忆快照读取失败：%s", exc)
                return MemorySnapshot()


MEMORY = MemoryStore(MEMORY_DIR, TEMPLATES_DIR)
