from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.api.middleware.auth import verify_token
from backend.api.routes.x_api_models import XPostOut, XSearchResponse
from backend.api.x_search_service import XSearchQuery, XSearchServiceError, run_x_search
from backend.common.logging import get_logger
from backend.common.x_budget import XBudgetError
from backend.config.settings import settings
from backend.core.s02_tools.builtin.x_client import XClientConfig, XClientError

logger = get_logger(component="x_api")

router = APIRouter(
    prefix="/api/x",
    tags=["x-search"],
    dependencies=[Depends(verify_token)],
)


def _x_config() -> XClientConfig:
    return XClientConfig(
        username=settings.twitter_username,
        email=settings.twitter_email,
        password=settings.twitter_password,
        proxy_url=settings.twitter_proxy_url,
        cookies_file=settings.twitter_cookies_file,
    )


@router.get("/searches", response_model=XSearchResponse)
async def search_x(
    response: Response,
    q: str = Query(min_length=1, max_length=200, description="搜索关键词"),
    days: int = Query(default=7, ge=1, le=365, description="只保留最近 N 天"),
    limit: int = Query(default=15, ge=1, le=50, description="最多返回条数"),
    type: Literal["Latest", "Top"] = Query(default="Latest", description="最新或热门"),
) -> XSearchResponse:
    query = XSearchQuery(query=q.strip(), days=days, limit=limit, search_type=type)
    result = await _run(query)
    if result.rate_limited and result.retry_after:
        response.headers["Retry-After"] = str(result.retry_after)
    return XSearchResponse(
        query=query.query,
        count=len(result.posts),
        rate_limited=result.rate_limited,
        retry_after=result.retry_after,
        cached=result.cached,
        results=[XPostOut.from_post(post) for post in result.posts],
    )


async def _run(query: XSearchQuery):
    try:
        return await run_x_search(_x_config(), query)
    except XBudgetError as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "X_BUDGET_EXCEEDED", "message": exc.reason},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except XClientError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "X_UPSTREAM_ERROR", "message": str(exc)},
        ) from exc
    except XSearchServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "X_SEARCH_FAILED", "message": str(exc)},
        ) from exc


__all__ = ["router"]
