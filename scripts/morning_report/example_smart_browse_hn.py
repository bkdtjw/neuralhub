"""HN 抓帖子示例。

运行: python -m scripts.morning_report.example_smart_browse_hn
"""

import asyncio

from backend.core.s02_tools.builtin.browser.smart_browse import smart_browse


async def main() -> None:
    async with smart_browse() as page:
        await page.goto("https://news.ycombinator.com/")
        comments_link = page.locator("td.subtext").first.locator("a").last
        comments = await comments_link.text_content()
        await comments_link.click()
        await page.wait_for_load_state("domcontentloaded")
        title = await page.title()
        await page.screenshot(path="/tmp/hn_first_post.png")
        print("title:", title, "url:", page.url, "comments:", comments or "0 comments")


if __name__ == "__main__":
    asyncio.run(main())
