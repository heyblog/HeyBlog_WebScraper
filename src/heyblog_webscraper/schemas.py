"""Validated data contracts for URL collection results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictInt,
    UrlConstraints,
    field_validator,
    model_serializer,
    model_validator,
)


HttpUrl = Annotated[
    AnyUrl,
    UrlConstraints(allowed_schemes=["http", "https"], max_length=8_192),
]
HttpStatusCode = Annotated[StrictInt, Field(ge=100, le=599)]


class _StrictSchema(BaseModel):
    """Shared validation policy for collector-owned data contracts."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )


class FeedInfo(_StrictSchema):
    """One feed advertised by the collected website."""

    url: HttpUrl = Field(
        description="网站 Feed 的 URL。"
    )
    format: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_-]*$",
        description="网站 Feed 的格式，例如 rss。",
    )
    title: str | None = Field(
        default=None,
        max_length=1_000,
        description="Feed 的标题",
    )


class WebsiteIcon(_StrictSchema):
    """Website icon metadata; an empty object represents an undiscovered icon."""

    url: HttpUrl | None = Field(
        default=None,
        description="网站图标的 URL",
    )
    type: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="网站图标的媒体类型",
    )

    @model_validator(mode="after")
    def require_complete_metadata(self) -> WebsiteIcon:
        if (self.url is None) != (self.type is None):
            raise ValueError("icon url and type must either both be set or both be absent")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_metadata(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, object]:
        serialized = handler(self)
        return {key: value for key, value in serialized.items() if value is not None}


class WebsiteInfo(_StrictSchema):
    """Metadata discovered from the target website."""

    title: str | None = Field(
        default=None,
        max_length=1_000,
        description="网站的 title",
    )
    description: str | None = Field(
        default=None,
        max_length=10_000,
        description="网站的 description",
    )
    icon: WebsiteIcon = Field(
        default_factory=WebsiteIcon,
        description=(
            "网站图标信息，包含 url 和 type"
        ),
    )
    feeds: list[FeedInfo] = Field(
        default_factory=list,
        max_length=100,
        description="网站的 Feed 信息，可能包含多个 Feed",
    )


class CollectionError(_StrictSchema):
    """A machine-readable, stage-specific collection failure."""

    stage: str = Field(
        default="unknown",
        min_length=1,
        max_length=100,
        description="发生错误的采集阶段。",
    )
    url: str | None = Field(
        default=None,
        max_length=8_192,
        description="发生错误时正在处理的 URL；不适用时为 None。",
    )
    message: str = Field(
        default="",
        min_length=1,
        max_length=2_000,
        description="供日志和诊断使用的错误说明。",
    )
    retryable: StrictBool = Field(
        default=False,
        description="该错误是否适合重试。",
    )


class BasicUrlInfo(_StrictSchema):
    """Structured representation of ``collect_basic_url_info`` JSON output."""

    schema_version: str = Field(
        default="2609141704v1",
        description=(
            "当前 URL 信息结构的版本号，采用 {YYMMDDHHMM}v{version} 编码，方便后续升级和兼容。"
        ),
    )

    status_code: HttpStatusCode | None = Field(
        default=None,
        description="HTTP 状态码；尚未获取响应时为 None。",
    )

    raw_url: str = Field(
        default=None,
        min_length=1,
        max_length=8_192,
        description="调用方传入的原始 URL。",
    )

    normalized_url: HttpUrl = Field(
        default=None,
        min_length=1,
        max_length=8_192,
        description="经过标准化处理的 URL。",
    )

    final_url: HttpUrl | None = Field(
        default=None,
        min_length=1,
        max_length=8_192,
        description="完成重定向后得到的最终 URL",
    )

    redirect_chain: list[HttpUrl] = Field(
        min_length=1,
        max_length=50,
        description="请求经历的重定向 URL 链；默认仅包含 normalized_url。",
    )

    fetched_at: datetime | None = Field(
        default=None,
        description=(
            "信息获取时间，以 UTC 时区的 ISO 8601 格式表示；"
            "尚未获取时为 None。"
        ),
    )

    website_info: WebsiteInfo = Field(
        default_factory=WebsiteInfo,
        description="从网站页面中提取的基础信息。",
    )

    errors: list[CollectionError] = Field(
        default_factory=list,
        max_length=100,
        description="采集过程中产生的结构化错误；没有错误时为 []。",
    )

    @field_validator("fetched_at")
    @classmethod
    def normalize_fetched_at_to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must include a timezone")
        return value.astimezone(UTC)


__all__ = [
    "BasicUrlInfo",
    "CollectionError",
    "FeedInfo",
    "WebsiteIcon",
    "WebsiteInfo",
]
