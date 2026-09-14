from __future__ import annotations

from heyblog_webscraper import RawFetchResult, collect_basic_url_info, normalize_url


class StubFetcher:
    def __init__(self, responses: dict[str, RawFetchResult]) -> None:
        self.responses = responses
        self.fetch_calls: list[tuple[str, float, int]] = []
        self.probe_calls: list[tuple[str, float]] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int, user_agent: str) -> RawFetchResult:
        del user_agent
        self.fetch_calls.append((url, timeout_seconds, max_bytes))
        return self.responses[url]

    def probe(self, url: str, *, timeout_seconds: float, user_agent: str) -> RawFetchResult:
        del user_agent
        self.probe_calls.append((url, timeout_seconds))
        return RawFetchResult(
            requested_url=url,
            final_url=url,
            status_code=404,
            headers={"content-type": "text/html"},
            elapsed_ms=1,
        )


def response(url: str, body: bytes, content_type: str, **headers: str) -> RawFetchResult:
    return RawFetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        headers={"content-type": content_type, **headers},
        body=body,
        elapsed_ms=2,
    )


def test_basic_collection_uses_fixed_scope_and_collects_icon_and_timing() -> None:
    home_url = "https://example.com/"
    feed_url = "https://example.com/feed.xml"
    about_url = "https://example.com/about"
    icon_url = "https://example.com/icon.png"
    home = b"""<html><head>
      <meta property="og:title" content="Example Blog">
      <meta name="description" content="A concise description">
      <meta name="generator" content="WordPress 6.8">
      <link rel="alternate" type="application/atom+xml" href="/feed.xml">
      <link rel="icon" href="/icon.png">
    </head><body><a href="/about">About</a><main>secret page text</main></body></html>"""
    feed = b"<feed xmlns='http://www.w3.org/2005/Atom'><title>Feed</title></feed>"
    about = b"<html><head><title>About us</title><meta name='description' content='Who we are'></head></html>"
    icon = b"\x89PNG\r\n\x1a\n"
    fetcher = StubFetcher(
        {
            home_url: response(home_url, home, "text/html; charset=utf-8", server="nginx"),
            feed_url: response(feed_url, feed, "application/atom+xml; charset=utf-8"),
            about_url: response(about_url, about, "text/html; charset=utf-8"),
            icon_url: response(icon_url, icon, "image/png"),
        }
    )

    result = collect_basic_url_info("HTTPS://Example.COM:443", fetcher=fetcher)

    assert result.info.requested_url == home_url
    assert result.info.page is not None
    assert len(result.info.page.visible_text) == 1
    assert result.info.page.metadata == {}
    assert result.info.page.raw_html is None
    assert result.info.articles == []
    assert result.info.feeds[0].url == feed_url
    assert result.info.related_pages[0].url == about_url
    assert result.icon is not None
    assert result.icon.source_url == icon_url
    assert result.icon.media_type == "image/png"
    assert result.icon.byte_size == len(icon)
    assert result.timing.request_count == 9
    assert result.timing.response_bytes == len(home) + len(feed) + len(about) + len(icon)
    assert result.timing.budget_exhausted is False
    assert all(timeout <= 4 for _, timeout, _ in fetcher.fetch_calls)
    assert fetcher.fetch_calls[0][2] == 1_048_576
    assert fetcher.fetch_calls[2][2] == 131_072
    assert fetcher.fetch_calls[3][2] == 1_048_576


def test_basic_collection_attempts_at_most_three_feed_candidates() -> None:
    home_url = "https://example.com/"
    home = b"<html><head><title>Example</title></head></html>"
    responses = {home_url: response(home_url, home, "text/html")}
    responses[home_url].truncated = True
    for path in ("feed", "feed/", "rss"):
        url = f"https://example.com/{path}"
        responses[url] = RawFetchResult(
            requested_url=url,
            final_url=url,
            status_code=404,
            headers={"content-type": "text/html"},
        )
    responses["https://example.com/favicon.ico"] = RawFetchResult(
        requested_url="https://example.com/favicon.ico",
        final_url="https://example.com/favicon.ico",
        status_code=404,
        headers={"content-type": "image/x-icon"},
    )
    fetcher = StubFetcher(responses)

    result = collect_basic_url_info(home_url, fetcher=fetcher)

    ignored = {home_url, "https://example.com/favicon.ico"}
    feed_fetches = [url for url, _, _ in fetcher.fetch_calls if url not in ignored]
    assert feed_fetches == [
        "https://example.com/feed",
        "https://example.com/feed/",
        "https://example.com/rss",
    ]
    assert len(result.info.feeds) == 3
    assert result.info.status == "partial"
    assert any(error.stage == "home" and error.code == "too_large" for error in result.info.errors)


def test_basic_collection_marks_an_exhausted_total_budget(monkeypatch) -> None:
    from heyblog_webscraper.collector import basic

    fetcher = StubFetcher({})
    monkeypatch.setattr(basic, "_TOTAL_TIMEOUT_SECONDS", 0)

    result = collect_basic_url_info("https://example.com/", fetcher=fetcher)

    assert result.info.status == "failed"
    assert result.timing.budget_exhausted is True
    assert result.timing.request_count == 0
    assert [error.stage for error in result.info.errors] == ["home", "budget"]
    assert fetcher.fetch_calls == []


def test_normalize_url_removes_duplicate_path_separators() -> None:
    assert normalize_url("HTTPS://Example.COM:443//a///b/../c") == "https://example.com/a/c"
