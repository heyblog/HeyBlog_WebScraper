"""URL normalization."""

from __future__ import annotations

import ipaddress
import posixpath
import re
import socket
from urllib.parse import quote, urlsplit, urlunsplit


def normalize_url(value: str) -> str:
    """Validate and normalize an absolute public HTTP(S) URL."""

    # 必须是字符串
    if not isinstance(value, str):
        raise ValueError("url must be a string")
    # 一定没空格
    value = value.strip()
    if not value or any(character.isspace() for character in value):
        raise ValueError("url must not be empty or contain whitespace")

    parsed = urlsplit(value)

    scheme = parsed.scheme.casefold()
    # 只允许http和https
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute public HTTP(S) URL")
    # 拒绝带有用户信息的URL
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url user information is not allowed")
    # 拒绝fragment
    if parsed.fragment:
        raise ValueError("url fragment is not allowed")
    # 确保没有非法port
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("url port is invalid")

    raw_host = parsed.hostname.casefold().rstrip(".")
    # 不允许localhost
    if raw_host == "localhost" or raw_host.endswith(".localhost"):
        raise ValueError("local URLs are not allowed")
    # 检查是否为公网地址
    try:
        address = ipaddress.ip_address(raw_host)
    except ValueError:
        try:
            socket.inet_aton(raw_host)
        except OSError:
            pass
        else:
            raise ValueError("numeric IP-like hostnames are not allowed") from None
        try:
            host = raw_host.encode("idna").decode("ascii").casefold()
        except UnicodeError as exc:
            raise ValueError("url host is invalid") from exc
    else:
        if not address.is_global:
            raise ValueError("private and local IP addresses are not allowed")
        host = raw_host

    # 规范化路径并返回
    if ":" in host:
        host = f"[{host}]"
    if port is not None and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    trailing_slash = path.endswith("/")
    path = posixpath.normpath(path)
    if not path.startswith("/"):
        path = f"/{path}"
    if trailing_slash and path != "/":
        path += "/"
    path = quote(path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="%=&?/:;+,%@!$'()*-._~")
    return urlunsplit((scheme, host, path, query, ""))


__all__ = ["normalize_url"]
