"""公开网页正文提取，包含基础 SSRF、重定向和响应体积防护。"""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

_TIMEOUT = 15
_MAX_RESPONSE_BYTES = 1024 * 1024
_ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "text/html",
    "text/plain",
    "text/xml",
}


def _validate_public_url(url: str) -> str:
    """验证 URL 只指向公网 HTTP(S) 的标准端口。"""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持完整的 http:// 或 https:// 公网地址")
    if parsed.username or parsed.password:
        raise ValueError("URL 不允许包含用户名或密码")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("URL 端口无效") from exc
    if port not in {80, 443}:
        raise ValueError("只允许访问 80 或 443 端口")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ValueError("不允许访问本机或局域网地址")

    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"域名无法解析：{hostname}") from exc
    if not addresses:
        raise ValueError(f"域名无法解析：{hostname}")

    for address in addresses:
        ip_text = address[4][0].split("%", 1)[0]
        if not ipaddress.ip_address(ip_text).is_global:
            raise ValueError("不允许访问本机、内网或保留地址")
    return url


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """在跟随重定向前再次验证目标地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        _validate_public_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


class _HTMLTextExtractor(HTMLParser):
    """从 HTML 中提取标题和可见文本。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        elif tag == "title" and self._ignored_depth == 0:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.text_parts.append(data)


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _open_url(request: urllib.request.Request):
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    return opener.open(request, timeout=_TIMEOUT)


def fetch_webpage(url: str, max_chars: int = 3000) -> str:
    """读取公开网页并返回适合模型消费的纯文本正文。"""
    url = (url or "").strip()
    if not url:
        return "Error: 网页地址为空"
    if len(url) > 2048:
        return "Error: 网页地址过长"
    max_chars = max(500, min(int(max_chars), 12000))

    try:
        _validate_public_url(url)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "text/html,text/plain,application/json,application/xml;q=0.9",
                "User-Agent": "Mozilla/5.0 (compatible; SimonAgent/0.1; +local-learning-agent)",
            },
        )
        with _open_url(request) as response:
            final_url = response.geturl()
            _validate_public_url(final_url)
            content_type = response.headers.get_content_type()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                return f"Error: 不支持的网页内容类型: {content_type}"
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                return "Error: 网页内容超过 1 MB，已拒绝读取"
            charset = response.headers.get_content_charset() or "utf-8"
            decoded = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        return f"Error: 网页请求失败（HTTP {exc.code}）"
    except urllib.error.URLError as exc:
        return f"Error: 网页连接失败: {getattr(exc, 'reason', exc)}"
    except (LookupError, OSError, TimeoutError, ValueError) as exc:
        return f"Error: {exc}"

    title = ""
    if content_type == "text/html":
        parser = _HTMLTextExtractor()
        try:
            parser.feed(decoded)
            parser.close()
        except Exception as exc:
            return f"Error: HTML 解析失败: {exc}"
        title = _normalize_text(" ".join(parser.title_parts))
        text = _normalize_text(" ".join(parser.text_parts))
    elif content_type == "application/json":
        try:
            text = json.dumps(json.loads(decoded), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            text = decoded.strip()
    else:
        text = _normalize_text(decoded)

    if not text:
        return "Error: 网页没有可读取的文本内容"
    truncated = len(text) > max_chars
    text = text[:max_chars].rstrip()
    lines = [f"网页地址: {final_url}"]
    if title:
        lines.append(f"网页标题: {title[:300]}")
    lines.extend(["正文:", text + ("...（已截断）" if truncated else "")])
    return "\n".join(lines)
