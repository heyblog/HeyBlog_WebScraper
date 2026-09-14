"""feed 解析公共辅助函数的参数化覆盖测试。"""

from __future__ import annotations

from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import pytest

from heyblog_webscraper.parsing import (
    common_feed_url_candidates,
    discover_feed_urls_from_html,
    is_feed_payload,
    parse_feed_articles,
)


def test_parse_feed_articles_supports_rss_atom_and_json_feed() -> None:
    feeds = (
        ("<rss><channel><item><link>/rss-post</link><title>RSS</title></item></channel></rss>", "application/rss+xml"),
        ("<feed xmlns='http://www.w3.org/2005/Atom'><entry><link href='/atom-post'/><title>Atom</title></entry></feed>", "application/atom+xml"),
        ('{"version":"https://jsonfeed.org/version/1.1","items":[{"url":"/json-post","title":"JSON"}]}', "application/feed+json"),
    )

    articles = [
        parse_feed_articles(payload, base_url="https://example.com/feed", content_type=content_type)[0]
        for payload, content_type in feeds
    ]

    assert [article.url for article in articles] == [
        "https://example.com/rss-post",
        "https://example.com/atom-post",
        "https://example.com/json-post",
    ]
    assert [article.title for article in articles] == ["RSS", "Atom", "JSON"]


def test_atom_entry_prefers_alternate_link_over_self() -> None:
    payload = (
        "<feed xmlns='http://www.w3.org/2005/Atom'><entry>"
        "<link rel='self' href='https://example.com/feed.xml'/>"
        "<link rel='enclosure' href='https://example.com/audio.mp3'/>"
        "<link rel='alternate' href='/post'/>"
        "<title>Atom</title>"
        "</entry></feed>"
    )

    articles = parse_feed_articles(payload, base_url="https://example.com/feed")

    assert [article.url for article in articles] == ["https://example.com/post"]


def test_atom_entry_prefers_full_content_over_summary() -> None:
    payload = """<feed xmlns='http://www.w3.org/2005/Atom'><entry>
      <link href='/post' rel='alternate'/><title>Atom</title>
      <content type='html'><![CDATA[<p>Full article paragraph.</p><p>More detail.</p>]]></content>
      <summary type='html'><![CDATA[Short summary.]]></summary>
    </entry></feed>"""

    (article,) = parse_feed_articles(payload, base_url="https://example.com/feed")

    assert article.content == "Full article paragraph. More detail."
    assert "Short summary." not in article.content


def test_rss_content_encoded_prefers_full_content_over_description() -> None:
    payload = """<rss xmlns:content='http://purl.org/rss/1.0/modules/content/'><channel><item>
      <link>/post</link><title>RSS</title>
      <description>Short description.</description>
      <content:encoded><![CDATA[<p>Full RSS article.</p><p>More detail.</p>]]></content:encoded>
    </item></channel></rss>"""

    (article,) = parse_feed_articles(payload, base_url="https://example.com/feed")

    assert article.content == "Full RSS article. More detail."
    assert "Short description." not in article.content


def test_rss_1_0_rdf_items_are_parsed() -> None:
    payload = (
        "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' "
        "xmlns='http://purl.org/rss/1.0/'>"
        "<channel rdf:about='https://example.com/'><title>Blog</title></channel>"
        "<item rdf:about='https://example.com/rdf-post'>"
        "<title>RDF</title><link>https://example.com/rdf-post</link>"
        "</item>"
        "</rdf:RDF>"
    )

    articles = parse_feed_articles(payload, base_url="https://example.com/feed")

    assert [article.url for article in articles] == ["https://example.com/rdf-post"]
    assert articles[0].title == "RDF"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mon, 01 Jan 2024 10:00:00 +0000", datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)),
        ("2024-01-01T10:00:00Z", datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)),
        ("2024-01-01T10:00:00+08:00", datetime(2024, 1, 1, 10, 0).replace(tzinfo=timezone.utc).astimezone(timezone.utc) if False else datetime.fromisoformat("2024-01-01T10:00:00+08:00")),
        ("not a date", None),
        ("", None),
    ],
)
def test_published_at_parsing_paths_and_fallback(raw: str, expected: datetime | None) -> None:
    payload = f"<rss><channel><item><link>/p</link><pubDate>{raw}</pubDate></item></channel></rss>"

    (article,) = parse_feed_articles(payload, base_url="https://example.com/")

    assert article.published_at == expected


def test_url_validator_filters_articles() -> None:
    payload = (
        "<rss><channel>"
        "<item><link>https://example.com/ok</link></item>"
        "<item><link>https://blocked.example/bad</link></item>"
        "</channel></rss>"
    )

    articles = parse_feed_articles(
        payload,
        base_url="https://example.com/",
        url_validator=lambda url: "blocked" not in url,
    )

    assert [article.url for article in articles] == ["https://example.com/ok"]


def test_max_items_and_item_chars_bounds() -> None:
    items = "".join(
        f"<item><link>/p{index}</link><description>{'x' * 50}</description></item>" for index in range(5)
    )
    payload = f"<rss><channel>{items}</channel></rss>"

    articles = parse_feed_articles(payload, base_url="https://example.com/", max_items=2, item_chars=10)

    assert len(articles) == 2
    assert all(len(article.content) <= 10 for article in articles)


@pytest.mark.parametrize("kwargs", [{"max_items": 0}, {"item_chars": 0}, {"max_items": -1}])
def test_non_positive_bounds_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        parse_feed_articles("<rss/>", base_url="https://example.com/", **kwargs)


def test_malformed_xml_raises_parse_error() -> None:
    with pytest.raises(ET.ParseError):
        parse_feed_articles("<rss><channel><item>", base_url="https://example.com/")


def test_malformed_json_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_feed_articles("{not json", base_url="https://example.com/", content_type="application/feed+json")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("<?xml version='1.0'?><rss version='2.0'><channel/></rss>", True),
        ("<rss version='2.0'>", True),
        ("<feed xmlns='http://www.w3.org/2005/Atom'>", True),
        ("﻿<?xml version='1.0'?><feed>", True),
        ('{"version": "https://jsonfeed.org/version/1.1", "items": []}', True),
        ("<!doctype html><html><body>hi</body></html>", False),
        ('{"version": "1.0"}', False),
        ("", False),
    ],
)
def test_is_feed_payload(payload: str, expected: bool) -> None:
    assert is_feed_payload(payload) is expected


def test_discover_feed_urls_from_html_dedupes_and_filters() -> None:
    html = (
        "<html><head>"
        "<link rel='alternate' type='application/rss+xml' href='/rss.xml'>"
        "<link rel='alternate' type='application/rss+xml' href='/rss.xml'>"
        "<link rel='alternate' type='application/atom+xml' href='/atom.xml'>"
        "<link rel='stylesheet' href='/style.css'>"
        "<link rel='alternate' type='text/html' href='/mobile'>"
        "</head></html>"
    )

    assert discover_feed_urls_from_html(html, base_url="https://example.com/") == [
        "https://example.com/rss.xml",
        "https://example.com/atom.xml",
    ]
    assert discover_feed_urls_from_html("", base_url="https://example.com/") == []


def test_common_feed_url_candidates_origin_only() -> None:
    candidates = common_feed_url_candidates("https://example.com/blog/post?a=1")

    assert candidates[0] == "https://example.com/feed"
    assert all(candidate.startswith("https://example.com/") for candidate in candidates)
    assert len(candidates) == 7
    assert common_feed_url_candidates("ftp://example.com/") == []
