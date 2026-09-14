from __future__ import annotations

from heyblog_webscraper.net import MetadataParser


def test_metadata_parser_extracts_title_description_and_icon() -> None:
    parser = MetadataParser()

    parser.feed(
        """<html><head>
        <title>Example Blog</title>
        <meta name="description" content="A useful website">
        <link rel="shortcut icon" href="/favicon.ico" type="image/x-icon">
        </head></html>"""
    )

    assert "".join(parser.title_parts) == "Example Blog"
    assert parser.description == "A useful website"
    assert parser.icon_href == "/favicon.ico"
    assert parser.icon_type == "image/x-icon"


def test_metadata_parser_collects_open_graph_fallbacks() -> None:
    parser = MetadataParser()

    parser.feed(
        """<html><head>
        <meta property="og:title" content="Open Graph title">
        <meta property="og:description" content="Open Graph description">
        <link rel="apple-touch-icon" href="/touch.png">
        </head></html>"""
    )

    assert parser.open_graph_title == "Open Graph title"
    assert parser.open_graph_description == "Open Graph description"
    assert parser.icon_href == "/touch.png"
    assert parser.icon_type is None


def test_metadata_parser_collects_supported_feed_links() -> None:
    parser = MetadataParser()
    parser.feed(
        """
        <link rel="alternate" type="application/rss+xml; charset=utf-8"
              href="/rss.xml" title=" Latest posts ">
        <link rel="feed" type="application/atom+xml" href="/atom.xml">
        <link rel="alternate" type="application/feed+json" href="/feed.json">
        <link rel="alternate" type="application/rdf+xml" href="/rss1.xml">
        <link rel="alternate" type="text/html" href="/archive">
        <link rel="stylesheet" type="application/rss+xml" href="/not-a-feed.xml">
        """
    )

    assert parser.feed_links == [
        ("/rss.xml", "rss", " Latest posts "),
        ("/atom.xml", "atom", None),
        ("/feed.json", "json", None),
        ("/rss1.xml", "rdf", None),
    ]
