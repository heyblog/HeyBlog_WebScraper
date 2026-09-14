"""Minimal URL information collection scaffold."""

from __future__ import annotations

from ..net import MetadataParser, normalize_url
from ..schemas import BasicUrlInfo, CollectionError, FeedInfo


def collect_basic_url_info(
    url: str,
) -> BasicUrlInfo:
    """Collect basic website information and return a validated result model."""

    from datetime import UTC, datetime
    from mimetypes import guess_type
    from urllib.error import HTTPError, URLError
    from urllib.parse import urljoin
    from urllib.request import HTTPRedirectHandler, Request, build_opener

    # 1. 规范化输入 URL，并创建字段完整的基础结果。
    normalized_url = normalize_url(url)
    result = BasicUrlInfo(
        status_code=None,
        raw_url=url,
        normalized_url=normalized_url,
        final_url=None,
        redirect_chain=[normalized_url],
        fetched_at=None,
        website_info={
            "title": None,
            "description": None,
            "icon": {},
            "feeds": [],
        },
        errors=[],
    )
    stage_failures: list[tuple[str, str | None, Exception, bool]] = []

    def remember_failure(
        stage: str,
        error_url: str | None,
        error: Exception,
        *,
        retryable: bool = False,
    ) -> None:
        if len(stage_failures) < 100:
            stage_failures.append((stage, error_url, error, retryable))

    def request_error_is_retryable(error: Exception) -> bool:
        if isinstance(error, HTTPError):
            status_code = error.code
            return isinstance(status_code, int) and (
                status_code in {408, 425, 429} or 500 <= status_code <= 599
            )
        return isinstance(error, (TimeoutError, URLError, OSError))

    # 2. 请求目标页面，将状态码、最终 URL 和重定向链写入 result。
    redirect_chain = [normalized_url]

    class RedirectRecorder(HTTPRedirectHandler):
        def redirect_request(
            self,
            request,
            response,
            code,
            message,
            headers,
            new_url,
        ):
            redirected_request = super().redirect_request(
                request,
                response,
                code,
                message,
                headers,
                new_url,
            )
            if redirected_request is not None:
                redirected_url = normalize_url(redirected_request.full_url)
                if len(redirect_chain) < 50:
                    redirect_chain.append(redirected_url)
            return redirected_request

    page_body = b""
    content_type = ""
    content_charset = "utf-8"
    final_url: str | None = None

    def record_response_location(response) -> None:
        nonlocal final_url

        result.status_code = response.getcode()
        final_url = normalize_url(response.geturl())
        result.final_url = final_url
        if redirect_chain[-1] != final_url and len(redirect_chain) < 50:
            redirect_chain.append(final_url)

    try:
        request = Request(
            normalized_url,
            headers={"User-Agent": "HeyBlog/0.1"},
        )
        opener = build_opener(RedirectRecorder())
        with opener.open(request, timeout=10.0) as response:
            record_response_location(response)
            page_body = response.read(1_048_577)[:1_048_576]
            content_type = response.headers.get("Content-Type", "")
            get_content_charset = getattr(response.headers, "get_content_charset", None)
            if callable(get_content_charset):
                content_charset = get_content_charset() or content_charset
    except HTTPError as response:
        try:
            with response:
                record_response_location(response)
        except Exception as error:
            remember_failure(
                "request",
                final_url or normalized_url,
                error,
                retryable=request_error_is_retryable(error),
            )
        remember_failure(
            "request",
            final_url or normalized_url,
            response,
            retryable=request_error_is_retryable(response),
        )
    except Exception as error:
        remember_failure(
            "request",
            final_url or normalized_url,
            error,
            retryable=request_error_is_retryable(error),
        )

    result.redirect_chain = redirect_chain

    # =========== 3. 从页面中提取基础元数据。===========

    def clean_text(value: str | None, max_length: int) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned[:max_length] or None

    if page_body and (not content_type or "html" in content_type.casefold()):
        try:
            page_html = page_body.decode(content_charset)
        except (LookupError, UnicodeDecodeError) as error:
            remember_failure("metadata", final_url, error)
            page_html = page_body.decode("utf-8", errors="replace")

        metadata_parser: MetadataParser | None = None
        try:
            metadata_parser = MetadataParser()
            metadata_parser.feed(page_html)
        except Exception as error:
            remember_failure("metadata", final_url, error)

        if metadata_parser is not None:
            # =========== 3.1 从页面中提取标题===========
            result.website_info.title = (
                clean_text("".join(metadata_parser.title_parts), 1_000)
                or clean_text(metadata_parser.open_graph_title, 1_000)
            )

            # =========== 3.2 从页面中提取描述===========
            result.website_info.description = (
                clean_text(metadata_parser.description, 10_000)
                or clean_text(metadata_parser.open_graph_description, 10_000)
            )

            # =========== 3.3 从页面中提取站点图标===========
            if metadata_parser.icon_href:
                icon_reference = metadata_parser.icon_href
                try:
                    icon_url = normalize_url(urljoin(final_url, icon_reference))
                    icon_type = clean_text(metadata_parser.icon_type, 255)
                    if icon_type:
                        icon_type = icon_type.partition(";")[0].strip().casefold()
                    else:
                        icon_type = guess_type(icon_url)[0]
                    if icon_type:
                        result.website_info.icon = {
                            "url": icon_url,
                            "type": icon_type,
                        }
                except Exception as error:
                    remember_failure("icon", icon_reference, error)

    else:
        metadata_parser = None

    # 4. 发现并整理网站公开的 RSS、Atom 等 Feed 信息。
    if metadata_parser is not None:
        discovered_feeds: list[FeedInfo] = []
        seen_feed_urls: set[str] = set()

        for feed_href, feed_format, feed_title in metadata_parser.feed_links:
            feed_reference = feed_href
            try:
                feed_reference = urljoin(final_url, feed_href)
                feed_url = normalize_url(feed_reference)
                feed = FeedInfo(
                    url=feed_url,
                    format=feed_format,
                    title=clean_text(feed_title, 1_000),
                )
            except Exception as error:
                remember_failure("feed", feed_reference, error)
                continue

            if feed_url in seen_feed_urls:
                continue

            seen_feed_urls.add(feed_url)
            discovered_feeds.append(feed)
            if len(discovered_feeds) == 100:
                break

        result.website_info.feeds = discovered_feeds

    # 5. 将各阶段异常转换为结构化错误，同时保留已经采集到的数据。
    result.errors = [
        CollectionError(
            stage=stage,
            url=error_url[:8_192] if error_url else None,
            message=(clean_text(str(error), 2_000) or type(error).__name__),
            retryable=retryable,
        )
        for stage, error_url, error, retryable in stage_failures
    ]

    # 6. 写入 UTC 采集时间，返回经过 Pydantic 校验的 BasicUrlInfo。
    result.fetched_at = datetime.now(UTC)

    return result


__all__ = ["collect_basic_url_info"]
