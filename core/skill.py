import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import SKILLS_DIR


logger = logging.getLogger(__name__)
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    description: str
    body: str
    path: Path
    tags: tuple[str, ...] = ()


class SkillLoader:
    """发现并按需提供本地 Markdown Skill，不在启动时注入完整正文。"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, SkillDefinition] = {}
        self.reload()

    def reload(self) -> None:
        """
        扫描发现所有技能
        """
        discovered: dict[str, SkillDefinition] = {}
        if not self.skills_dir.is_dir():
            self.skills = discovered
            return

        for path in sorted(self.skills_dir.rglob("SKILL.md")):
            try:
                metadata, body = self._parse_frontmatter(path.read_text(encoding="utf-8"))
                skill = self._build_definition(path, metadata, body)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                logger.warning("技能文件无效，已跳过 %s：%s", path, exc)
                continue
            if skill.name in discovered:
                logger.warning("技能名称重复，已保留首个定义：%s", skill.name)
                continue
            discovered[skill.name] = skill
        self.skills = discovered

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
        match = _FRONTMATTER.match(text.replace("\r\n", "\n"))
        if not match:
            return {}, text.strip()
        header, body = match.groups()
        try:
            import yaml

            metadata = yaml.safe_load(header) or {}
        except ModuleNotFoundError:
            metadata = {}
            for line in header.splitlines():
                key, separator, value = line.partition(":")
                if separator:
                    metadata[key.strip()] = value.strip().strip("\"'")
        except Exception as exc:
            raise ValueError(f"frontmatter 解析失败：{exc}") from exc
        if not isinstance(metadata, dict):
            raise ValueError("frontmatter 必须是键值对象")
        return metadata, body.strip()

    @staticmethod
    def _build_definition(path: Path, metadata: dict[str, Any], body: str) -> SkillDefinition:
        name = metadata.get("name", path.parent.name)
        description = metadata.get("description", "No description")
        if not isinstance(name, str) or not _SKILL_NAME.fullmatch(name):
            raise ValueError("name 必须使用小写字母、数字和连字符")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description 必须是非空文本")
        if not body:
            raise ValueError("Skill 正文不能为空")

        raw_tags = metadata.get("tags", ())
        if isinstance(raw_tags, str):
            tags = tuple(tag.strip() for tag in raw_tags.split(",") if tag.strip())
        elif isinstance(raw_tags, list):
            tags = tuple(str(tag).strip() for tag in raw_tags if str(tag).strip())
        else:
            tags = ()
        return SkillDefinition(name, description.strip(), body, path, tags)

    def get_descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"
        lines = []
        for skill in self.skills.values():
            suffix = f" [{','.join(skill.tags)}]" if skill.tags else ""
            lines.append(f"  - {skill.name}: {skill.description}{suffix}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if skill is None:
            available = ", ".join(self.skills) or "none"
            return f"Error: Unknown skill '{name}'. Available: {available}"
        return f'<skill name="{skill.name}">\n{skill.body}\n</skill>'


SKILL_LOADER = SkillLoader(SKILLS_DIR)
