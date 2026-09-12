import uuid
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str) -> None:
    """同目录写临时文件后替换目标，避免留下不完整内容。"""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def to_jsonable(value: Any) -> Any:
    """把 SDK/Pydantic 对象递归转换为标准 JSON 数据。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return to_jsonable(value.model_dump())
    return str(value)
