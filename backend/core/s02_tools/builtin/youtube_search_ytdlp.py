"""YouTube 搜索工具 - 基于 yt-dlp (无需 API Key)"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult


class YouTubeSearchError(Exception):
    """YouTube 搜索错误"""


class YouTubeVideoInfo:
    """YouTube 视频信息"""
    def __init__(self, data: dict):
        self.id = data.get("id", "")
        self.title = data.get("title", "")
        self.uploader = data.get("uploader", "")
        self.view_count = data.get("view_count", 0)
        self.duration = data.get("duration", 0)
        self.upload_date = data.get("upload_date", "")
        self.description = data.get("description", "")
        self.url = f"https://www.youtube.com/watch?v={self.id}"
        self.subtitle_text = ""

    @property
    def duration_formatted(self) -> str:
        """格式化时长"""
        seconds = self.duration
        minutes, seconds = divmod(max(seconds, 0), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _get_proxy_url() -> str:
    """获取代理 URL"""
    import os
    return os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7890"


def _parse_yt_dlp_json_output(line: str) -> dict | None:
    """解析 yt-dlp 的 JSON 输出"""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def search_videos_sync(query: str, max_results: int = 10) -> list[YouTubeVideoInfo]:
    """同步搜索 YouTube 视频"""
    import subprocess

    proxy = _get_proxy_url()
    search_query = f"ytsearch{max_results}:{query}"

    cmd = [
        "yt-dlp",
        "--proxy", proxy,
        "--dump-json",
        "--flat-playlist",
        "--playlist-end", str(max_results),
        search_query
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            raise YouTubeSearchError(f"yt-dlp 错误: {result.stderr}")

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            data = _parse_yt_dlp_json_output(line)
            if data:
                videos.append(YouTubeVideoInfo(data))

        return videos
    except subprocess.TimeoutExpired:
        raise YouTubeSearchError("搜索超时")
    except FileNotFoundError:
        raise YouTubeSearchError("yt-dlp 未安装，请先安装 yt-dlp")
    except Exception as e:
        raise YouTubeSearchError(f"搜索失败: {e}")


def get_video_details_sync(video_id: str) -> dict:
    """获取视频详细信息"""
    import subprocess

    proxy = _get_proxy_url()
    url = f"https://www.youtube.com/watch?v={video_id}"

    cmd = [
        "yt-dlp",
        "--proxy", proxy,
        "--dump-json",
        "--no-download",
        url
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {}

        lines = result.stdout.strip().split("\n")
        for line in lines:
            if line:
                return json.loads(line)
        return {}
    except Exception:
        return {}


def extract_subtitles_sync(video_id: str, max_duration: int = 1200) -> str:
    """提取视频字幕（仅对短视频）"""
    import subprocess
    import os
    import tempfile

    # 先检查视频时长
    details = get_video_details_sync(video_id)
    duration = details.get("duration", 0)

    if duration > max_duration:
        return f"[视频时长 {duration//60} 分钟，超过 {max_duration//60} 分钟限制，跳过字幕提取]"

    proxy = _get_proxy_url()
    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "yt-dlp",
            "--proxy", proxy,
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", "zh,en,zh-CN,zh-TW",
            "--skip-download",
            "--sub-format", "json3",
            "-o", f"{tmpdir}/%(id)s",
            url
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            # 查找生成的字幕文件
            for fname in os.listdir(tmpdir):
                if fname.endswith(".json3"):
                    fpath = os.path.join(tmpdir, fname)
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        # 解析 json3 格式
                        events = data.get("events", [])
                        texts = []
                        for event in events:
                            if "segs" in event:
                                for seg in event["segs"]:
                                    if "utf8" in seg:
                                        texts.append(seg["utf8"])
                        return " ".join(texts).strip()

            return "[未找到字幕]"

        except Exception as e:
            return f"[字幕提取失败: {e}]"


async def search_videos(query: str, max_results: int = 10) -> list[YouTubeVideoInfo]:
    """异步搜索 YouTube 视频"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_videos_sync, query, max_results)


async def extract_subtitles(video_id: str, max_duration: int = 1200) -> str:
    """异步提取字幕"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, extract_subtitles_sync, video_id, max_duration)


def create_youtube_search_ytdlp_tool() -> tuple[ToolDefinition, ToolExecuteFn]:
    """创建 YouTube 搜索工具（基于 yt-dlp）"""

    definition = ToolDefinition(
        name="youtube_search",
        description="搜索 YouTube 视频并提取字幕。基于 yt-dlp，无需 API Key。",
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "最多返回视频数，默认 10，最大 20"},
                "extract_subtitles": {"type": "boolean", "description": "是否提取字幕（仅对20分钟内视频），默认 true"},
                "subtitles_max_duration": {"type": "integer", "description": "提取字幕的最大视频时长（秒），默认 1200（20分钟）"},
            },
            required=["query"],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            query = str(args.get("query", "")).strip()
            if not query:
                return ToolResult(output="错误：搜索关键词不能为空", is_error=True)

            max_results = min(int(args.get("max_results", 10)), 20)
            extract_subs = bool(args.get("extract_subtitles", True))
            max_duration = int(args.get("subtitles_max_duration", 1200))

            # 搜索视频
            videos = await search_videos(query, max_results)

            if not videos:
                return ToolResult(output=f'YouTube 搜索: "{query}"\n\n未找到符合条件的视频。')

            # 提取字幕（仅前3个视频）
            if extract_subs:
                for video in videos[:3]:
                    video.subtitle_text = await extract_subtitles(video.id, max_duration)

            # 格式化输出
            output = _format_results(query, videos, extract_subs)
            return ToolResult(output=output)

        except YouTubeSearchError as e:
            return ToolResult(output=f"YouTube 搜索错误: {e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"搜索失败: {e}", is_error=True)

    return definition, execute


def _format_results(query: str, videos: list[YouTubeVideoInfo], has_subtitles: bool) -> str:
    """格式化搜索结果"""
    lines = [
        f'🎬 YouTube 搜索结果: "{query}"',
        f"共找到 {len(videos)} 个视频",
        ""
    ]

    for i, video in enumerate(videos, 1):
        lines.append(f"{i}. {video.title}")
        lines.append(f"   👤 频道: {video.uploader}")
        lines.append(f"   👁️ 播放量: {video.view_count:,}")
        lines.append(f"   ⏱️ 时长: {video.duration_formatted}")
        lines.append(f"   📅 上传日期: {video.upload_date or '未知'}")
        lines.append(f"   🔗 {video.url}")
        if has_subtitles and video.subtitle_text:
            preview = video.subtitle_text[:300] + "..." if len(video.subtitle_text) > 300 else video.subtitle_text
            lines.append(f"   📝 字幕摘要: {preview}")
        lines.append("")

    return "\n".join(lines)


# 字幕提取工具
def create_youtube_subtitle_tool() -> tuple[ToolDefinition, ToolExecuteFn]:
    """创建 YouTube 字幕提取工具"""

    definition = ToolDefinition(
        name="youtube_subtitle",
        description="提取 YouTube 视频的字幕/自动字幕。支持通过 URL 或视频 ID 提取。",
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "video_url": {"type": "string", "description": "YouTube 视频 URL 或视频 ID"},
                "language": {"type": "string", "description": "优先语言代码，如 zh, en，默认自动选择"},
                "max_duration": {"type": "integer", "description": "最大允许的视频时长（秒），默认 1200（20分钟）"},
            },
            required=["video_url"],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            url = str(args.get("video_url", "")).strip()
            if not url:
                return ToolResult(output="错误：视频 URL 不能为空", is_error=True)

            # 提取视频 ID
            video_id = _extract_video_id(url)
            if not video_id:
                return ToolResult(output=f"错误：无法从 URL 提取视频 ID: {url}", is_error=True)

            max_duration = int(args.get("max_duration", 1200))

            # 获取视频信息
            details = await asyncio.get_event_loop().run_in_executor(
                None, get_video_details_sync, video_id
            )

            if not details:
                return ToolResult(output=f"错误：无法获取视频信息: {url}", is_error=True)

            title = details.get("title", "未知标题")
            duration = details.get("duration", 0)

            if duration > max_duration:
                return ToolResult(
                    output=f"视频: {title}\n时长: {duration//60} 分钟\n超过 {max_duration//60} 分钟限制，跳过字幕提取。"
                )

            # 提取字幕
            subtitle = await extract_subtitles(video_id, max_duration)

            output = f"""📝 视频字幕提取

📺 标题: {title}
⏱️ 时长: {duration//60} 分钟
🔗 {url}

{'='*50}
{subtitle}
{'='*50}
"""
            return ToolResult(output=output)

        except Exception as e:
            return ToolResult(output=f"字幕提取失败: {e}", is_error=True)

    return definition, execute


def _extract_video_id(url: str) -> str:
    """从 URL 提取视频 ID"""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    host = parsed.netloc.lower()

    # youtu.be/VIDEO_ID
    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0]

    # youtube.com/watch?v=VIDEO_ID
    if "youtube.com" in host:
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_id:
            return query_id

        # /embed/VIDEO_ID 或 /shorts/VIDEO_ID
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts"}:
            return path_parts[1]

    # 直接是视频 ID (11位)
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url

    return ""


__all__ = [
    "create_youtube_search_ytdlp_tool",
    "create_youtube_subtitle_tool",
    "YouTubeVideoInfo",
    "YouTubeSearchError",
]
