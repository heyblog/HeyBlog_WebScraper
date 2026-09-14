"""HTML metadata extraction."""

from __future__ import annotations

from html.parser import HTMLParser


_FEED_FORMATS_BY_MEDIA_TYPE = {
    "application/atom+xml": "atom",
    "application/feed+json": "json",
    "application/rdf+xml": "rdf",
    "application/rss+xml": "rss",
    "text/atom+xml": "atom",
    "text/rss+xml": "rss",
}


class MetadataParser(HTMLParser):
    """Extract basic website metadata from an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_parts: list[str] = []
        self.open_graph_title: str | None = None
        self.description: str | None = None
        self.open_graph_description: str | None = None
        self.icon_href: str | None = None
        self.icon_type: str | None = None
        self.feed_links: list[tuple[str, str, str | None]] = []

    def handle_starttag(
        self,
        tag: str,
        attributes: list[tuple[str, str | None]],
    ) -> None:
        attributes_by_name = dict(attributes)

        if tag == "title":
            self.in_title = True
            return

        if tag == "meta":
            key = (
                attributes_by_name.get("name")
                or attributes_by_name.get("property")
                or ""
            ).casefold()
            content = attributes_by_name.get("content")
            if key == "description" and self.description is None:
                self.description = content
            elif key == "og:description" and self.open_graph_description is None:
                self.open_graph_description = content
            elif key == "og:title" and self.open_graph_title is None:
                self.open_graph_title = content
            return

        if tag != "link":
            return

        relations = set(
            (attributes_by_name.get("rel") or "").casefold().split()
        )
        href = attributes_by_name.get("href")
        media_type = (
            attributes_by_name.get("type") or ""
        ).partition(";")[0].strip().casefold()
        feed_format = _FEED_FORMATS_BY_MEDIA_TYPE.get(media_type)

        if href and feed_format and relations.intersection({"alternate", "feed"}):
            self.feed_links.append(
                (href, feed_format, attributes_by_name.get("title"))
            )

        if self.icon_href is None and (
            "icon" in relations or "apple-touch-icon" in relations
        ):
            self.icon_href = attributes_by_name.get("href")
            self.icon_type = attributes_by_name.get("type")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


__all__ = ["MetadataParser"]
