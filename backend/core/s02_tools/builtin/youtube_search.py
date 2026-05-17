from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .youtube_client import YouTubeClientError, YouTubeSearchRequest, YouTubeVideo, fetch_subtitle, search_videos


class YouTubeSearchToolError(Exception):
    """YouTube search tool error."""


class YouTubeSearchArgs(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=20)
    days: int = Field(default=0, ge=0, le=365)
    with_subtitles: bool = True

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("搜索关键词不能为空")
        return query


def create_youtube_search_tool(
    api_key: str,
    proxy_url: str = "",
) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="youtube_search",
        description="搜索 YouTube 视频并提取自动字幕。",
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "最多返回视频数，默认 5，最大 20"},
                "days": {"type": "integer", "description": "仅保留最近 N 天的视频，0 表示不限日期"},
                "with_subtitles": {"type": "boolean", "description": "是否提取字幕，默认 true"},
            },
            required=["query"],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            params = _parse_args(args)
            videos = await search_videos(
                YouTubeSearchRequest(
                    query=params.query,
                    api_key=api_key,
                    max_results=params.max_results,
                    days=params.days,
                    proxy_url=proxy_url,
                )
            )
            if params.with_subtitles:
                await _attach_subtitles(videos, proxy_url)
            return ToolResult(output=_format_report(params, videos))
        except (YouTubeClientError, YouTubeSearchToolError) as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"YouTube 搜索失败：{exc}", is_error=True)

    return definition, execute


def _parse_args(args: dict[str, object]) -> YouTubeSearchArgs:
    try:
        return YouTubeSearchArgs.model_validate(args)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "参数不合法")
        raise YouTubeSearchToolError(f"参数错误：{message}") from exc


async def _attach_subtitles(videos: list[YouTubeVideo], proxy_url: str) -> None:
    try:
        for video in videos[:3]:
            video_id = _extract_video_id(video.url)
            if video_id:
                video.subtitle_text = await fetch_subtitle(video_id, proxy_url=proxy_url)
    except Exception as exc:  # noqa: BLE001
        raise YouTubeSearchToolError(f"字幕提取失败：{exc}") from exc


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/", maxsplit=1)[0]
    if "youtube.com" not in host:
        return ""
    query_id = parse_qs(parsed.query).get("v", [""])[0]
    if query_id:
        return query_id
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts"}:
        return path_parts[1]
    return ""


def _format_report(params: YouTubeSearchArgs, videos: list[YouTubeVideo]) -> str:
    range_text = f"最近 {params.days} 天" if params.days > 0 else "不限日期"
    header = f'YouTube 搜索结果: "{params.query}" ({range_text}，共 {len(videos)} 个视频)'
    if not videos:
        return f"{header}\n\n未找到符合条件的视频。"
    sections = [header]
    for index, video in enumerate(videos, start=1):
        sections.append(
            "\n".join(
                [
                    "",
                    f"{index}. {video.title}",
                    f"   频道: {video.channel} | 播放量: {video.view_count:,} | 时长: {_format_duration(video.duration_seconds)}",
                    f"   上传日期: {video.upload_date or '未知'}",
                    f"   链接: {video.url}",
                    _format_subtitle_line(video.subtitle_text),
                ]
            )
        )
    return "\n".join(sections)


def _format_duration(duration_seconds: int) -> str:
    minutes, seconds = divmod(max(duration_seconds, 0), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _format_subtitle_line(subtitle_text: str) -> str:
    preview = subtitle_text.replace("\n", " ") if subtitle_text else "未提取字幕"
    return f"   字幕摘要: {preview}"


__all__ = ["YouTubeSearchArgs", "YouTubeSearchToolError", "create_youtube_search_tool"]
