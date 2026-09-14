"""Minimal HeyBlog WebScraper API."""

from .collector import collect_basic_url_info
from .net import normalize_url


__all__ = ["collect_basic_url_info", "normalize_url"]
