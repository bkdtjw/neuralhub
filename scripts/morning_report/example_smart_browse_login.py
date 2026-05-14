"""GitHub storage_state 登录态示例。

运行: python -m scripts.morning_report.example_smart_browse_login
"""

import asyncio

from backend.core.s02_tools.builtin.browser.smart_browse import smart_browse


async def main() -> None:
    async with smart_browse(user_id="default", domain="github.com") as page:
        await page.goto("https://github.com/")
        menu = page.locator(
            "button[aria-label='Open user navigation menu'], "
            "summary[aria-label='View profile and more'], "
            "summary[aria-label='Account and profile']"
        )
        print("github_logged_in:", await menu.count() > 0)


if __name__ == "__main__":
    asyncio.run(main())
