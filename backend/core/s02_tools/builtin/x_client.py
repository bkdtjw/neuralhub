from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from twikit import Client, TooManyRequests  # type: ignore[import-not-found, import-untyped]

from .x_models import XClientConfig, XPost, XSearchOptions
from .x_post_utils import collect_posts, tweet_to_post, utcnow
from .x_raw_search import search_raw_posts, supports_raw_search
from .x_twikit_patches import apply_x_runtime_patches, reset_search_timeline_metadata_cache


class XClientError(Exception):
    """X/Twitter client error."""


class XRateLimitError(XClientError):
    """X/Twitter search hit a rate limit."""

    def __init__(self, partial_posts: list[XPost], retry_after_seconds: int | None) -> None:
        self.partial_posts = partial_posts
        self.retry_after_seconds = retry_after_seconds
        super().__init__("X/Twitter 搜索触发频率限制")


_cached_client: Client | None = None
_cached_config_hash = ""
_cached_loop_id: int | None = None
# 缓存判定→构建(含 login+写 cookies 文件)非原子，并发首建会双 login/竞写文件；按事件循环各持一把锁
# 串行化该临界区(本模块支持多 loop，锁不能跨 loop 复用)。
_client_locks: dict[int, asyncio.Lock] = {}


def _client_lock() -> asyncio.Lock:
    return _client_locks.setdefault(id(asyncio.get_running_loop()), asyncio.Lock())


async def search_x_posts(
    query: str,
    config: XClientConfig,
    options: XSearchOptions | None = None,
) -> list[XPost]:
    try:
        resolved_options = options or XSearchOptions()
        client = await _get_client(config)
        _dedupe_client_cookies(client)
        if supports_raw_search(client):
            return await search_raw_posts(
                client, query, resolved_options, _build_query, _dedupe_client_cookies
            )
        page = await _search_tweets_with_retry(
            client,
            _build_query(query, resolved_options.days),
            resolved_options.search_type,
            min(resolved_options.max_results, 20),
        )
        posts = _collect_posts(page, resolved_options.max_results)
        while len(posts) < resolved_options.max_results:
            try:
                next_page = await page.next()
            except TooManyRequests as exc:
                raise _build_rate_limit_error(posts, exc) from exc
            except Exception:
                break
            if not next_page:
                break
            page = next_page
            posts.extend(_collect_posts(page, resolved_options.max_results - len(posts)))
        return posts[: resolved_options.max_results]
    except XRateLimitError:
        raise
    except XClientError:
        raise
    except TooManyRequests as exc:
        raise _build_rate_limit_error([], exc) from exc
    except Exception as exc:
        raise XClientError(f"X/Twitter 搜索失败：{exc}") from exc


async def _get_client(config: XClientConfig) -> Client:
    global _cached_client, _cached_config_hash, _cached_loop_id
    try:
        apply_x_runtime_patches()
        auth_info_1, auth_info_2 = _resolve_auth_inputs(config)
        config_hash = _build_config_hash(config)
        loop_id = id(asyncio.get_running_loop())
        if _cached_client and _cached_config_hash == config_hash and _cached_loop_id == loop_id:
            return _cached_client
        async with _client_lock():
            # 锁内二次判定：等锁期间他人可能已建好同配置客户端，避免重复 login / 竞写 cookie 文件。
            if _cached_client and _cached_config_hash == config_hash and _cached_loop_id == loop_id:
                return _cached_client
            if _cached_client and _cached_loop_id != loop_id:
                await _close_cached_client(_cached_client)
            client = _create_twikit_client(config)
            await client.login(
                auth_info_1=auth_info_1,
                auth_info_2=auth_info_2,
                password=config.password,
                cookies_file=config.cookies_file,
            )
            _dedupe_client_cookies(client)
            _cached_client, _cached_config_hash, _cached_loop_id = client, config_hash, loop_id
            return client
    except Exception as exc:
        raise _normalize_login_error(exc) from exc


def _create_twikit_client(config: XClientConfig) -> Client:
    try:
        return Client("en-US", proxy=config.proxy_url or None, trust_env=False)
    except TypeError:
        return Client("en-US", proxy=config.proxy_url or None)


def _build_config_hash(config: XClientConfig) -> str:
    return "|".join(
        [config.username, config.email, config.password, config.proxy_url, config.cookies_file]
    )


def _resolve_auth_inputs(config: XClientConfig) -> tuple[str, str | None]:
    username = config.username.strip()
    email = config.email.strip()
    if username:
        return username, email or None
    if email:
        return email, None
    raise XClientError("X/Twitter 登录失败，请至少配置用户名或邮箱")


def _build_rate_limit_error(posts: list[XPost], exc: TooManyRequests) -> XRateLimitError:
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(retry_after, (int, float)):
        return XRateLimitError(posts, max(int(retry_after - time.time()) + 1, 1))
    return XRateLimitError(posts, None)


def _normalize_login_error(exc: Exception) -> XClientError:
    message = str(exc)
    if "Cloudflare" in message or "blocked" in message.lower():
        return XClientError("X/Twitter 登录被 Cloudflare 拦截，请先在浏览器登录并刷新 cookie 文件")
    return XClientError("X/Twitter 登录失败，请检查用户名/邮箱/密码配置")


async def _search_tweets_with_retry(client: Client, query: str, search_type: str, count: int):
    last_error: Exception | None = None
    for _ in range(3):
        try:
            return await client.search_tweet(query, search_type, count=count)
        except Exception as exc:
            if 'status: 404, message: ""' not in str(exc):
                raise
            last_error = exc
            reset_search_timeline_metadata_cache()
            _dedupe_client_cookies(client)
    if last_error is not None:
        raise last_error
    raise RuntimeError("search_tweet retry failed without an exception")


def _dedupe_client_cookies(client: Client) -> None:
    if not hasattr(client, "http") or not hasattr(client.http, "cookies"):
        return
    unique: dict[str, str] = {}
    for cookie in client.http.cookies.jar:
        if cookie.name not in unique:
            unique[cookie.name] = cookie.value
    client.http.cookies = list(unique.items())


async def _close_cached_client(client: Client) -> None:
    if not hasattr(client, "http") or not hasattr(client.http, "aclose"):
        return
    try:
        await client.http.aclose()
    except Exception:
        return


def _build_query(query: str, days: int) -> str:
    return f"{query.strip()} since:{(_utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')}"


def _collect_posts(page: object, limit: int) -> list[XPost]:
    return collect_posts(page, limit)


_tweet_to_post = tweet_to_post

def _utcnow():
    return utcnow()


__all__ = [
    "XClientConfig",
    "XClientError",
    "XPost",
    "XRateLimitError",
    "XSearchOptions",
    "_build_query",
    "_close_cached_client",
    "_collect_posts",
    "_create_twikit_client",
    "_dedupe_client_cookies",
    "_normalize_login_error",
    "_resolve_auth_inputs",
    "_search_tweets_with_retry",
    "_tweet_to_post",
    "_utcnow",
    "search_raw_posts",
    "search_x_posts",
    "supports_raw_search",
]
