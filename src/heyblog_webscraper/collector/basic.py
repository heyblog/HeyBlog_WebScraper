"""Minimal URL information collection scaffold."""

from __future__ import annotations

from ..net import normalize_url


def collect_basic_url_info(
    url: str,
    *,
    fetcher: object | None = None,
) -> dict[str, object]:
    """Return an empty URL information structure for incremental development."""

    del fetcher
    normalized_url = normalize_url(url)

    return {
        "schema_version": "2609141704v1", # 当前url信息结构的版本号，为{YYMMDDHHMM}_v{version}的格式，便于后续升级和兼容
        "status_code": None, # HTTP状态码，None表示未获取
        "raw_url": url, # 原始URL，未经处理
        "normalized_url": normalized_url, # 标准化后的URL
        "final_url": None, # 最终URL（因为可能经过重定向）
        "redirect_chain": [ # 重定向链，包含所有中间URL，默认为[normalized url]
                normalized_url
            ],
        "fetched_at": None, # 表示获取这些信息的时间，保存为UTC时间的ISO 8601格式字符串
        "website_info": {
            "title": None, # 网站的title，如果没有则为None
            "description": None, # 网站的description，如果没有则为None
            "icon": {}, # 网站的icon信息，包含url和type，如果没有则为{}
            "feeds": [
                {
                    "url": "https://example.com/feed.xml", # 网站feed的url
                    "format": "rss", # 网站feed的格式
                    "title": "example", # feed的title
                },
            ], # 网站的feed信息，可能存在多个，如果没有则为[]
        },

        # "resources": [], 考虑是否要提前爬取一些网页，例如about，friends，links等
        # "technology_signals": {
        #     "generator": None,
        #     "generator_family": None,
        #     "headers": {},
        # },
        "errors": []
    }


__all__ = ["collect_basic_url_info"]
