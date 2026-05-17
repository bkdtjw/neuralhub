from __future__ import annotations

import re

from pydantic import BaseModel


class SiteGuide(BaseModel):
    site_id: str
    domain: str
    preferred_start_url: str
    instructions: str


JD_GUIDE = SiteGuide(
    site_id="jd",
    domain="jd.com",
    preferred_start_url="https://www.jd.com?from=pc_search_sd",
    instructions=(
        "京东浏览说明书：\n"
        "- 在当前远程环境中，裸 https://www.jd.com/ 可能跳转到 corporate.jd.com；"
        "这不代表京东购物站不可访问。需要京东购物首页时优先使用 "
        "https://www.jd.com?from=pc_search_sd。\n"
        "- 如果用户给了具体搜索页或商品页，优先访问用户给的具体链接；"
        "若跳转到 passport.jd.com 登录页，视为登录态缺失。\n"
        "- 京东首次登录以扫码二维码为主。遇到二维码、验证码、安全验证或风控页时，"
        "立即返回核心截图并停止，不要等待几分钟、不要反复重试、不要尝试密码登录。\n"
        "- 用户在本地 Chrome/手机完成扫码并通过 Cookie Sync 同步后，重新执行原任务，"
        "应使用 domain=jd.com 加载已有登录态。\n"
        "- 注意：storage_state 文件存在只代表有历史 cookie，不代表已经登录成功。"
        "必须通过页面上的账号、退出入口、购物车/我的京东等真实账号迹象确认登录态；"
        "如果仍看到登录页、扫码页、passport.jd.com、页面异常、内容太火爆或切换账号，"
        "视为登录态失效或风控，不要声称已登录。\n"
        "- 如果已登录，先确认页面上的账号/购物车/我的京东等登录迹象；"
        "涉及帐号上下文时可查看购物车、我的京东、足迹或订单等已有记录，"
        "不要只基于未登录公共页下结论。\n"
        "- 目标是快速完成：优先直达搜索/商品/登录态检查页面；"
        "一旦确认需要人工扫码或验证，尽快返回 need_human。"
    ),
)

_GUIDES = (JD_GUIDE,)
_URL_RE = re.compile(r"https?://[^\s\"'<>，。；]+", re.IGNORECASE)


def resolve_site_guide(task: str, domain: str = "") -> SiteGuide | None:
    text = f"{task} {domain}".lower()
    for guide in _GUIDES:
        if guide.domain in text or guide.site_id in text or _contains_zh_site(text, guide.site_id):
            return guide
    return None


def resolve_initial_url(task: str, guide: SiteGuide | None) -> str:
    explicit = _first_url(task)
    if guide is None:
        return explicit
    if _is_jd_bare_home(explicit):
        return guide.preferred_start_url
    return explicit or guide.preferred_start_url


def _first_url(task: str) -> str:
    match = _URL_RE.search(task)
    return match.group(0).rstrip(")") if match else ""


def _is_jd_bare_home(url: str) -> bool:
    return url.rstrip("/") in {"https://www.jd.com", "http://www.jd.com"}


def _contains_zh_site(text: str, site_id: str) -> bool:
    return site_id == "jd" and "京东" in text


__all__ = ["SiteGuide", "resolve_initial_url", "resolve_site_guide"]
