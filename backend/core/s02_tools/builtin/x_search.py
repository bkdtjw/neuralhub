from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .x_client import (
    XClientConfig,
    XClientError,
    XPost,
    XRateLimitError,
    XSearchOptions,
    search_x_posts,
)

SearchType = Literal["Latest", "Top"]
_BEIJING = ZoneInfo("Asia/Shanghai")


class XSearchToolError(Exception):
    """X/Twitter search tool error."""


class XSearchArgs(BaseModel):
    query: str
    max_results: int = Field(default=15, ge=1, le=50)
    days: int = Field(default=30, ge=1, le=365)
    search_type: SearchType = "Latest"

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("搜索关键词不能为空")
        return query


def create_x_search_tool(config: XClientConfig) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="x_search",
        description="Search and crawl recent tweets from X/Twitter",
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "query": {"type": "string", "description": "Search keywords"},
                "max_results": {
                    "type": "integer",
                    "description": "Max tweets to return, default 15, max 50",
                },
                "days": {
                    "type": "integer",
                    "description": "Only keep tweets from last N days, default 30",
                },
                "search_type": {
                    "type": "string",
                    "description": "Search type: Latest or Top, default Latest",
                },
            },
            required=["query"],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        params: XSearchArgs | None = None
        try:
            params = _parse_args(args)
            posts = await search_x_posts(
                params.query,
                config,
                XSearchOptions(
                    max_results=params.max_results,
                    days=params.days,
                    search_type=params.search_type,
                ),
            )
            return ToolResult(output=_format_report(params, posts))
        except XRateLimitError as exc:
            if params is None:
                return ToolResult(output=str(exc), is_error=True)
            return ToolResult(
                output=_format_report(
                    params,
                    exc.partial_posts,
                    retry_after_seconds=exc.retry_after_seconds,
                ),
                is_error=False,
            )
        except (XClientError, XSearchToolError) as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:
            return ToolResult(output=f"X/Twitter 搜索失败：{exc}", is_error=True)

    return definition, execute


def _parse_args(args: dict[str, object]) -> XSearchArgs:
    try:
        return XSearchArgs.model_validate(args)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "参数不合法")
        raise XSearchToolError(f"参数错误：{message}") from exc


def _format_report(
    params: XSearchArgs,
    posts: list[XPost],
    retry_after_seconds: int | None = None,
) -> str:
    suffix = ", rate-limited" if retry_after_seconds is not None else ""
    header = (
        f'X/Twitter search results: "{params.query}" '
        f"(last {params.days} days, {len(posts)} tweets found{suffix})"
    )
    if not posts:
        empty_text = (
            "No matching tweets found. Try broadening your search keywords "
            "or extending the time range."
        )
        if retry_after_seconds is not None:
            empty_text = (
                "[Note: Twitter rate limit reached before results were returned]\n\n"
                + empty_text
            )
        return f"{header}\n\n{empty_text}"
    sections = [header]
    if retry_after_seconds is not None:
        note = "[Note: Twitter rate limit reached, showing partial results]"
        if retry_after_seconds > 0:
            note = f"{note} Retry after about {retry_after_seconds}s."
        sections.extend(["", note])
    for index, post in enumerate(posts, start=1):
        sections.extend(
            [
                "",
                (
                    f"{index}. @{post.author_handle} - {post.author_name} "
                    f"({_format_date(post.created_at)})"
                ),
                f"   {post.text}",
                (
                    f"   likes: {post.likes:,} | retweets: {post.retweets:,} "
                    f"| replies: {post.replies:,} | views: {post.views:,}"
                ),
                f"   {post.url}",
            ]
        )
    return "\n".join(sections)


def _format_date(created_at: str) -> str:
    try:
        return (
            datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
            .astimezone(_BEIJING)
            .strftime("%Y-%m-%d")
        )
    except ValueError:
        return created_at


__all__ = ["XSearchArgs", "XSearchToolError", "create_x_search_tool"]
