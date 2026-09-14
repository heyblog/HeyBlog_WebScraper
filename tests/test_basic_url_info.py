from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import Message
import urllib.request
from urllib.error import HTTPError

from heyblog_webscraper import BasicUrlInfo, collect_basic_url_info, normalize_url


class StubResponse:
    def __init__(
        self,
        url: str,
        body: bytes = b"",
        *,
        read_error: Exception | None = None,
    ) -> None:
        self.url = url
        self.body = body
        self.read_error = read_error
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def getcode(self) -> int:
        return 200

    def geturl(self) -> str:
        return self.url

    def read(self, _size: int) -> bytes:
        if self.read_error is not None:
            raise self.read_error
        return self.body

    def __enter__(self) -> StubResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class StubOpener:
    def __init__(
        self,
        body: bytes = b"",
        *,
        error: Exception | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.body = body
        self.error = error
        self.read_error = read_error
        self.opened_urls: list[str] = []

    def open(self, request, *, timeout: float) -> StubResponse:
        assert timeout == 10.0
        self.opened_urls.append(request.full_url)
        if self.error is not None:
            raise self.error
        return StubResponse(
            request.full_url,
            self.body,
            read_error=self.read_error,
        )


def install_stub_opener(
    monkeypatch,
    body: bytes = b"",
    *,
    error: Exception | None = None,
    read_error: Exception | None = None,
) -> StubOpener:
    opener = StubOpener(body, error=error, read_error=read_error)
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda _handler: opener,
    )
    return opener


def test_collect_basic_url_info_returns_validated_model(monkeypatch) -> None:
    install_stub_opener(monkeypatch)

    result = collect_basic_url_info("HTTPS://Example.COM:443")

    assert isinstance(result, BasicUrlInfo)
    assert result.raw_url == "HTTPS://Example.COM:443"
    assert str(result.normalized_url) == "https://example.com/"
    assert [str(url) for url in result.redirect_chain] == ["https://example.com/"]
    assert result.website_info.feeds == []


def test_collect_basic_url_info_records_utc_fetch_time(monkeypatch) -> None:
    install_stub_opener(monkeypatch)
    before = datetime.now(UTC)

    result = collect_basic_url_info("https://example.com")

    after = datetime.now(UTC)
    assert result.fetched_at is not None
    assert result.fetched_at.utcoffset() == timedelta(0)
    assert before <= result.fetched_at <= after


def test_collect_basic_url_info_serializes_to_the_existing_payload(monkeypatch) -> None:
    install_stub_opener(monkeypatch)

    result = collect_basic_url_info("https://example.com")
    payload = result.model_dump(mode="json")
    serialized_fetched_at = payload.pop("fetched_at")

    assert isinstance(serialized_fetched_at, str)
    assert datetime.fromisoformat(
        serialized_fetched_at.replace("Z", "+00:00")
    ) == result.fetched_at
    assert payload == {
        "schema_version": "2609141704v2",
        "status_code": 200,
        "raw_url": "https://example.com",
        "normalized_url": "https://example.com/",
        "final_url": "https://example.com/",
        "redirect_chain": ["https://example.com/"],
        "website_info": {
            "title": None,
            "description": None,
            "icon": {},
            "feeds": [],
        },
        "errors": [],
    }


def test_collect_basic_url_info_discovers_and_normalizes_feed_links(monkeypatch) -> None:
    page = b"""<html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml"
            title="  Example   RSS  ">
      <link rel="alternate" type="application/atom+xml"
            href="https://feeds.example.com/atom.xml">
      <link rel="feed" type="application/feed+json" href="feed.json">
      <link rel="alternate" type="application/rss+xml"
            href="https://example.com/feed.xml" title="Duplicate">
      <link rel="alternate" type="text/html" href="/archive">
      <link rel="stylesheet" type="application/rss+xml" href="/style.xml">
      <link rel="icon" type="image/png" href="javascript:alert(2)">
      <link rel="alternate" type="application/rss+xml" href="javascript:alert(1)">
    </head></html>"""
    opener = install_stub_opener(monkeypatch, page)

    result = collect_basic_url_info("https://example.com/blog/")

    assert [feed.model_dump(mode="json") for feed in result.website_info.feeds] == [
        {
            "url": "https://example.com/feed.xml",
            "format": "rss",
            "title": "Example RSS",
        },
        {
            "url": "https://feeds.example.com/atom.xml",
            "format": "atom",
            "title": None,
        },
        {
            "url": "https://example.com/blog/feed.json",
            "format": "json",
            "title": None,
        },
    ]
    assert result.website_info.icon.model_dump(mode="json") == {}
    assert [error.stage for error in result.errors] == ["icon", "feed"]
    assert all(error.retryable is False for error in result.errors)
    assert opener.opened_urls == ["https://example.com/blog/"]


def test_collect_basic_url_info_returns_structured_http_error(monkeypatch) -> None:
    url = "https://example.com/"
    http_error = HTTPError(
        url,
        503,
        "Service Unavailable",
        Message(),
        None,
    )
    install_stub_opener(monkeypatch, error=http_error)

    result = collect_basic_url_info(url)

    assert result.status_code == 503
    assert str(result.final_url) == url
    assert result.website_info.title is None
    assert len(result.errors) == 1
    assert result.errors[0].stage == "request"
    assert result.errors[0].url == url
    assert "503" in result.errors[0].message
    assert result.errors[0].retryable is True


def test_collect_basic_url_info_returns_structured_timeout(monkeypatch) -> None:
    install_stub_opener(monkeypatch, error=TimeoutError("request timed out"))

    result = collect_basic_url_info("https://example.com")

    assert result.status_code is None
    assert result.final_url is None
    assert result.redirect_chain == [result.normalized_url]
    assert result.errors[0].model_dump() == {
        "stage": "request",
        "url": "https://example.com/",
        "message": "request timed out",
        "retryable": True,
    }


def test_response_read_failure_preserves_status_and_final_url(monkeypatch) -> None:
    install_stub_opener(monkeypatch, read_error=OSError("connection reset"))

    result = collect_basic_url_info("https://example.com")

    assert result.status_code == 200
    assert str(result.final_url) == "https://example.com/"
    assert result.website_info.feeds == []
    assert result.errors[0].stage == "request"
    assert result.errors[0].retryable is True


def test_metadata_failure_preserves_already_parsed_fields(
    monkeypatch,
) -> None:
    from heyblog_webscraper.collector import basic

    page = b"""<html><head>
      <title>Partial result</title>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml">
    </head></html>"""
    install_stub_opener(monkeypatch, page)
    original_feed = basic.MetadataParser.feed

    def parse_then_fail(parser, html: str) -> None:
        original_feed(parser, html)
        raise RuntimeError("parser failed after collecting metadata")

    monkeypatch.setattr(basic.MetadataParser, "feed", parse_then_fail)

    result = collect_basic_url_info("https://example.com")

    assert result.website_info.title == "Partial result"
    assert str(result.website_info.feeds[0].url) == "https://example.com/feed.xml"
    assert result.errors[0].stage == "metadata"
    assert result.errors[0].retryable is False


def test_normalize_url_removes_duplicate_path_separators() -> None:
    assert normalize_url("HTTPS://Example.COM:443//a///b/../c") == "https://example.com/a/c"
