"""SimonAgent 内置工具函数的公共入口。"""

from .calculator import calculate
from .search import web_search
from .webpage import fetch_webpage
from .workspace import read_workspace_file, search_workspace

__all__ = (
    "calculate",
    "web_search",
    "fetch_webpage",
    "search_workspace",
    "read_workspace_file",
)
