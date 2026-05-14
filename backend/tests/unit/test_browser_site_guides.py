from __future__ import annotations

from backend.core.s02_tools.builtin.browser_agent.site_guides import (
    resolve_initial_url,
    resolve_site_guide,
)


def test_resolve_jd_site_guide_from_chinese_task() -> None:
    guide = resolve_site_guide("用浏览器查看京东商品价格")

    assert guide is not None
    assert guide.domain == "jd.com"
    assert "corporate.jd.com" in guide.instructions
    assert "storage_state 文件存在只代表有历史 cookie" in guide.instructions
    assert "扫码" in guide.instructions


def test_jd_bare_home_uses_shopping_entry() -> None:
    guide = resolve_site_guide("打开 https://www.jd.com/")

    assert resolve_initial_url("打开 https://www.jd.com/", guide) == (
        "https://www.jd.com?from=pc_search_sd"
    )


def test_jd_specific_product_url_is_preserved() -> None:
    guide = resolve_site_guide("京东 https://item.jd.com/100012043978.html")

    assert resolve_initial_url("京东 https://item.jd.com/100012043978.html", guide) == (
        "https://item.jd.com/100012043978.html"
    )
