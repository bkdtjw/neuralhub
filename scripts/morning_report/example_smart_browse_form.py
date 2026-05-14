"""example.com 截图尺寸 sanity check。

运行: python -m scripts.morning_report.example_smart_browse_form
"""

import asyncio
import struct
from pathlib import Path

from backend.core.s02_tools.builtin.browser.smart_browse import smart_browse

VIEWPORT = (1280, 720)
SCREENSHOT_PATH = Path("/tmp/example_smart_browse_form.png")


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    return struct.unpack(">II", data[16:24])


async def main() -> None:
    async with smart_browse(viewport=VIEWPORT, device_scale_factor=1.0) as page:
        await page.goto("https://example.com")
        await page.screenshot(path=str(SCREENSHOT_PATH))
    assert _png_size(SCREENSHOT_PATH) == VIEWPORT
    print("screenshot:", SCREENSHOT_PATH, "size:", VIEWPORT)


if __name__ == "__main__":
    asyncio.run(main())
