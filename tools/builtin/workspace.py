"""限定在项目安全文本范围内的源码检索与按行读取工具。"""

from __future__ import annotations

from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]

_TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "htmlcov",
    "logs",
    "memory",
    "sessions",
    "venv",
}
_BLOCKED_FILES = {".env", "user.md"}
_MAX_FILE_BYTES = 512 * 1024
_MAX_LINE_CHARS = 240


def _relative_allowed_file(path: Path, root: Path) -> Path | None:
    """返回安全的相对路径；不安全或不支持的文件返回 None。"""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None

    lowered_parts = {part.casefold() for part in relative.parts[:-1]}
    # 文件路径经过的目录和黑名单有交集 → 拒绝。
    if lowered_parts & _EXCLUDED_DIRS:
        return None
    # 文件名和黑名单有交集 → 拒绝。
    if relative.name.casefold() in _BLOCKED_FILES:
        return None
    # 文件扩展名不在白名单内 → 拒绝。
    if relative.suffix.casefold() not in _TEXT_SUFFIXES:
        return None
    # 路径不是普通文件 → 拒绝。
    if path.is_symlink() or not path.is_file():
        return None
    try:
        # 文件大小超过限制 → 拒绝。
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
    except OSError:
        return None
    return relative


def _iter_text_files(root: Path):
    """按相对路径顺序遍历允许读取的文本文件。"""
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        relative = _relative_allowed_file(path, root)
        if relative is not None:
            yield path, relative


def search_workspace(
    query: str,
    max_results: int = 10,
    *,
    root: Path = WORKSPACE_ROOT,
) -> str:
    """在允许的项目文本文件中进行不区分大小写的字面量检索。"""
    query = (query or "").strip()
    if not query:
        return "Error: 检索关键词为空"
    if len(query) > 200:
        return "Error: 检索关键词不能超过 200 个字符"

    max_results = max(1, min(int(max_results), 20))
    root = Path(root).resolve()
    matches: list[str] = []
    needle = query.casefold()

    for path, relative in _iter_text_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, 1):
            if needle not in line.casefold():
                continue
            snippet = " ".join(line.strip().split())
            if len(snippet) > _MAX_LINE_CHARS:
                snippet = snippet[:_MAX_LINE_CHARS].rstrip() + "..."
            matches.append(f"{relative.as_posix()}:{line_number}: {snippet}")
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    if not matches:
        return f"项目中未找到包含「{query}」的文本。"
    return f"项目检索「{query}」（返回 {len(matches)} 条）：\n" + "\n".join(matches)


def read_workspace_file(
    path: str,
    start_line: int = 1,
    max_lines: int = 120,
    *,
    root: Path = WORKSPACE_ROOT,
) -> str:
    """按行读取项目内允许访问的 UTF-8 文本文件。"""
    path = (path or "").strip().replace("\\", "/")
    if not path:
        return "Error: 文件路径为空"

    relative_input = Path(path)
    if relative_input.is_absolute():
        return "Error: 只允许使用项目内相对路径"

    try:
        root = Path(root).resolve()
        candidate = (root / relative_input).resolve()
    except (OSError, ValueError):
        return "Error: 文件路径无效"
    relative = _relative_allowed_file(candidate, root)
    if relative is None:
        return "Error: 文件不存在、类型不受支持或不允许访问"

    start_line = max(1, int(start_line))
    max_lines = max(1, min(int(max_lines), 200))
    try:
        lines = candidate.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return "Error: 文件不是有效的 UTF-8 文本"
    except OSError as exc:
        return f"Error: 文件读取失败: {exc}"

    if start_line > len(lines) and lines:
        return f"Error: 起始行 {start_line} 超出文件总行数 {len(lines)}"

    selected = lines[start_line - 1:start_line - 1 + max_lines]
    end_line = start_line + len(selected) - 1
    header = f"文件: {relative.as_posix()}（第 {start_line}-{end_line} 行，共 {len(lines)} 行）"
    numbered = [f"{number:>4} | {line}" for number, line in enumerate(selected, start_line)]
    return header + ("\n" + "\n".join(numbered) if numbered else "\n(空文件)")
