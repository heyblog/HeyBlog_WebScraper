"""Minimal HeyBlog WebScraper API."""

from .collector import collect_basic_url_info
from .net import normalize_url
from .schemas import BasicUrlInfo


__all__ = ["BasicUrlInfo", "collect_basic_url_info", "normalize_url"]
