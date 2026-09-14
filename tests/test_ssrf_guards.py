"""SSRF 防护测试：URL 字面校验、DNS 解析校验、重定向逐跳校验（review 六-2/六-17）。

被测能力全部位于网络层 :mod:`heyblog_webscraper.net`：

- :func:`validate_public_http_url`：字面层拦截非 http(s)、用户信息、片段、
  本地主机名与私有/本地 IP（含十进制/十六进制/八进制/IPv6 变体）。
- :func:`validate_resolved_public_host`：在字面校验之上追加 DNS 解析校验。
- :class:`_SafeRedirectHandler`：跟随每一跳重定向前重新校验目标主机。
"""

from __future__ import annotations

import socket

import pytest

from heyblog_webscraper import validate_public_http_url
from heyblog_webscraper.net import validate_resolved_public_host
from heyblog_webscraper.net.client import _SafeRedirectHandler


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",  # decimal form of 127.0.0.1
        "http://0x7f000001/",  # hex form of 127.0.0.1
        "http://0177.0.0.1/",  # octal-dotted form of 127.0.0.1
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://localhost/",
        "http://api.localhost/",
        "http://user:pass@example.com/",
        "ftp://example.com/",
        "http://exa mple.com/",
    ],
)
def test_validate_public_http_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_http_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://example.com/blog",
        "http://example.com:8080/path?a=1",
    ],
)
def test_validate_public_http_url_accepts_public_targets(url: str) -> None:
    assert validate_public_http_url(url) == url


def test_resolved_host_check_blocks_domain_pointing_at_private_ip(monkeypatch) -> None:
    def fake_getaddrinfo(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="private or local"):
        validate_resolved_public_host("https://internal.corp.example/")


def test_resolved_host_check_allows_public_resolution(monkeypatch) -> None:
    def fake_getaddrinfo(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    validate_resolved_public_host("https://example.com/")


def test_redirect_to_private_string_target_is_rejected() -> None:
    handler = _SafeRedirectHandler()
    with pytest.raises(ValueError, match="private and local"):
        handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/admin")


def test_redirect_to_domain_resolving_to_private_ip_is_rejected(monkeypatch) -> None:
    def fake_getaddrinfo(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.10", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    handler = _SafeRedirectHandler()
    with pytest.raises(ValueError, match="private or local"):
        handler.redirect_request(None, None, 302, "Found", {}, "https://rebind.example/")
