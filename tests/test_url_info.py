from __future__ import annotations

from datetime import UTC, datetime
import socket

import pytest

from heyblog_webscraper import (
    FetchStatus,
    RawFetchResult,
    UrlInfoOptions,
    UrlValidationError,
    collect_url_info,
    normalize_url,
    validate_public_http_url,
)
from heyblog_webscraper.net import validate_resolved_public_host


class StubFetcher:
    def __init__(self, responses: dict[str, RawFetchResult | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
        user_agent: str,
    ) -> RawFetchResult:
        del timeout_seconds, max_bytes, user_agent
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def response(
    url: str,
    body: str,
    content_type: str = "text/html; charset=utf-8",
    *,
    headers: dict[str, str] | None = None,
    status_code: int = 200,
) -> RawFetchResult:
    return RawFetchResult(
        requested_url=url,
        final_url=url,
        status_code=status_code,
        headers={"content-type": content_type, "server": "unit-test", **(headers or {})},
        body=body.encode(),
        elapsed_ms=5,
    )


def test_options_presets_keep_one_schema_with_different_budgets() -> None:
    assert UrlInfoOptions.standard().max_feed_items == 20
    assert UrlInfoOptions.for_model().max_feed_items == 0
    assert UrlInfoOptions.for_model().fetch_about_page is False
    assert UrlInfoOptions.for_agent().max_feed_items is None
    assert UrlInfoOptions.for_agent().enrich_feed_articles is True
    assert UrlInfoOptions.full().probe_common_paths is True


def test_collect_html_page_feed_and_about_into_stable_json() -> None:
    home_url = "https://example.com/"
    feed_url = "https://example.com/feed.xml"
    about_url = "https://example.com/about"
    home = """
    <html lang="zh-CN"><head>
      <title> Example Blog </title>
      <meta name="description" content="A useful blog">
      <meta name="keywords" content="Python, databases">
      <meta name="generator" content="WordPress 6.8">
      <meta property="og:type" content="website">
      <link rel="canonical" href="/">
      <link rel="icon" href="/favicon.ico">
      <link rel="alternate" type="application/rss+xml" href="/feed.xml">
    </head><body><article>Latest post</article><a href="/about">About</a></body></html>
    """
    feed = """
    <rss><channel><title>Example Feed</title><item>
      <title>Post 1</title><link>/posts/1</link>
      <description>Article summary</description><pubDate>Fri, 05 Sep 2026 12:00:00 GMT</pubDate>
    </item></channel></rss>
    """
    fetcher = StubFetcher(
        {
            home_url: response(home_url, home),
            feed_url: response(feed_url, feed, "application/rss+xml; charset=utf-8"),
            about_url: response(about_url, "<html><title>About</title><body>About the author</body></html>"),
        }
    )

    result = collect_url_info(
        home_url,
        options=UrlInfoOptions.standard().model_copy(update={"probe_common_paths": False}),
        fetcher=fetcher,
    )
    payload = result.model_dump(mode="json")

    assert result.status == "success"
    assert result.fetch.status == FetchStatus.OK
    assert result.page is not None
    assert result.page.title == "Example Blog"
    assert result.page.description == "A useful blog"
    assert result.page.language == "zh-CN"
    assert result.page.canonical_url == home_url
    assert result.page.icon_url == "https://example.com/favicon.ico"
    assert result.page.category_hints == ["Python", "databases"]
    assert result.page.markup.article_count == 1
    assert result.page.markup.has_feed_autodiscovery is True
    assert result.page.markup.generator == "wordpress 6.8"
    assert result.selected_feed_url == feed_url
    assert result.feeds[0].format == "RSS"
    assert result.feeds[0].title == "Example Feed"
    assert result.articles[0].url == "https://example.com/posts/1"
    assert result.articles[0].description == "Article summary"
    assert result.articles[0].published_at == datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    assert result.related_pages[0].visible_text == "About About the author"
    assert payload["schema_version"] == "1.0"
    assert payload["errors"] == []
    assert fetcher.calls == [home_url, feed_url, about_url]


def test_feed_input_is_parsed_and_longer_article_page_replaces_summary() -> None:
    feed_url = "https://example.com/feed"
    article_url = "https://example.com/post"
    feed = """
    <rss><channel><item><title>Post</title><link>/post</link>
    <description>Short excerpt.</description></item></channel></rss>
    """
    article = """
    <html><body><nav>Navigation</nav><article>
    Full article paragraph one. Full article paragraph two. More context follows.
    </article></body></html>
    """
    fetcher = StubFetcher(
        {
            feed_url: response(feed_url, feed, "application/rss+xml"),
            article_url: response(article_url, article),
        }
    )

    result = collect_url_info(feed_url, options=UrlInfoOptions.for_agent(), fetcher=fetcher)

    assert result.resource_kind == "feed"
    assert result.page is None
    assert result.selected_feed_url == feed_url
    assert result.articles[0].content.startswith("Full article paragraph one.")
    assert "Navigation" not in result.articles[0].content
    assert result.articles[0].content_source == "article_page"
    assert fetcher.calls == [feed_url, article_url]


def test_subresource_failure_returns_partial_result_without_losing_home_page() -> None:
    home_url = "https://example.com/"
    feed_url = "https://example.com/feed.xml"
    home = '<html><title>Example</title><link rel="alternate" type="application/rss+xml" href="/feed.xml"></html>'
    fetcher = StubFetcher({home_url: response(home_url, home), feed_url: TimeoutError("slow feed")})

    result = collect_url_info(
        home_url,
        options=UrlInfoOptions.standard().model_copy(
            update={"fetch_about_page": False, "probe_common_paths": False}
        ),
        fetcher=fetcher,
    )

    assert result.status == "partial"
    assert result.page is not None and result.page.title == "Example"
    assert result.selected_feed_url is None
    assert result.errors[0].stage == "feed"
    assert result.errors[0].code == "timeout"
    assert result.errors[0].retryable is True


def test_feed_discovery_uses_link_header_then_falls_back_to_common_paths() -> None:
    home_url = "https://example.com/"
    header_feed = "https://example.com/broken-feed"
    common_feed = "https://example.com/feed"
    home = "<html><title>Example</title></html>"
    feed = "<rss><channel><title>Fallback Feed</title></channel></rss>"
    fetcher = StubFetcher(
        {
            home_url: response(
                home_url,
                home,
                headers={"link": '</broken-feed>; rel="alternate"; type="application/rss+xml"'},
            ),
            header_feed: response(header_feed, "missing", status_code=404),
            common_feed: response(common_feed, feed, "application/rss+xml"),
        }
    )

    result = collect_url_info(
        home_url,
        options=UrlInfoOptions.standard().model_copy(
            update={"fetch_about_page": False, "probe_common_paths": False}
        ),
        fetcher=fetcher,
    )

    assert result.status == "partial"
    assert result.selected_feed_url == common_feed
    assert [item.discovery_source for item in result.feeds] == ["http_link_header", "common_path"]
    assert result.feeds[0].fetch.status_code == 404
    assert result.feeds[1].is_selected is True
    assert result.errors[0].stage == "feed"
    assert fetcher.calls == [home_url, header_feed, common_feed]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "http://127.0.0.1/",
        "http://2130706433/",
        "http://user:pass@example.com/",
        "https://example.com/#fragment",
        "https://exa mple.com/",
    ],
)
def test_public_url_validation_rejects_unsafe_or_noncanonical_inputs(url: str) -> None:
    with pytest.raises(UrlValidationError):
        validate_public_http_url(url)


def test_normalize_url_normalizes_host_port_path_and_query() -> None:
    assert normalize_url("HTTPS://Example.COM:443/a/../b?q=hello%20world") == (
        "https://example.com/b?q=hello%20world"
    )


def test_normalize_url_preserves_encoded_separators_and_ipv6_brackets() -> None:
    assert normalize_url("https://example.com/a%2Fb?q=x%2Fy") == "https://example.com/a%2Fb?q=x%2Fy"
    assert normalize_url("https://[2606:4700:4700::1111]:443/") == "https://[2606:4700:4700::1111]/"


def test_resolved_host_validation_rejects_private_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0))],
    )

    with pytest.raises(UrlValidationError, match="private or local"):
        validate_resolved_public_host("https://internal.example/")
