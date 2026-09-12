"""带响应校验和输出限长的 Tavily 搜索工具。"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TAVILY_API_URL = "https://api.tavily.com/search"
_TIMEOUT = 15  # 秒
_MAX_QUERY_CHARS = 300
_MAX_SNIPPET_CHARS = 800
_MAX_RESPONSE_BYTES = 1024 * 1024
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class TavilyConfigError(Exception):
    """Tavily 未配置或配置无效（调用方应转换为 Error 字符串）。"""


def _get_tavily_api_key() -> str:
    """读取 Tavily Key；直接导入工具包时也能按需加载项目 .env。"""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key and _ENV_PATH.is_file():
        try:
            from dotenv import load_dotenv
        except ModuleNotFoundError as exc:
            raise TavilyConfigError(
                "缺少依赖 python-dotenv，请先执行 pip install -r requirements.txt"
            ) from exc
        load_dotenv(_ENV_PATH, override=False)
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    return api_key


def tavily_request(payload: dict[str, Any]) -> dict[str, Any]:
    """发送一次 Tavily /search 请求，返回解析后的 JSON。

    失败时抛出异常（TavilyConfigError / PermissionError / 其他网络异常），
    由调用方决定如何转换为对用户友好的错误信息。
    payload 中无需包含 api_key，本函数自动注入。
    """
    api_key = _get_tavily_api_key()
    if not api_key or api_key.casefold().startswith(("your_", "replace_", "xxx")):
        raise TavilyConfigError(
            "未配置 TAVILY_API_KEY。请到 https://app.tavily.com 注册获取 Key，"
            "并填入 SimonAgent/.env 的 TAVILY_API_KEY 后重试。"
        )

    # api_key 最后写入，避免调用方 payload 意外覆盖真实配置。
    body = json.dumps({**payload, "api_key": api_key}).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_API_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "SimonAgent/0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise RuntimeError("Tavily 响应超过 1 MB，已拒绝读取")
            data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise PermissionError("Tavily API Key 无效或无权限，请检查 .env 中的 TAVILY_API_KEY。") from e
        raise RuntimeError(f"Tavily 请求失败（HTTP {e.code}）") from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise RuntimeError(f"Tavily 网络连接失败：{reason}") from e
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"Tavily 返回了无效响应：{e}") from e

    if not isinstance(data, dict):
        raise RuntimeError("Tavily 返回格式错误：顶层数据不是 JSON object")
    return data


def _clean_text(value: object, max_chars: int) -> str:
    """把第三方响应安全地转换为紧凑文本并限制长度。"""
    text = " ".join(str(value or "").split())
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def web_search(query: str, max_results: int = 5) -> str:
    """用 Tavily 执行搜索，返回格式化的纯文本结果。"""
    query = (query or "").strip()
    if not query:
        return "Error: 搜索关键词为空"
    if len(query) > _MAX_QUERY_CHARS:
        return f"Error: 搜索关键词不能超过 {_MAX_QUERY_CHARS} 个字符"

    try:
        data = tavily_request({
            "query": query,
            "max_results": max(1, min(int(max_results), 10)),
        })
    except Exception as e:
        return f"Error: {e}"

    results = data.get("results", [])
    if not isinstance(results, list):
        return "Error: Tavily 返回格式错误：results 不是数组"
    if not results:
        return f"未找到与「{query}」相关的结果。"

    lines = [f"搜索关键词: {query}（共 {len(results)} 条）"]
    for i, item in enumerate(results, 1):
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title") or "(无标题)", 200)
        url = _clean_text(item.get("url"), 2048)
        snippet = _clean_text(item.get("content"), _MAX_SNIPPET_CHARS)
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    if len(lines) == 1:
        return f"未找到与「{query}」相关的有效结果。"
    return "\n".join(lines)
