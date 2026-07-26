"""NotoSansSC 中文字体子集化：生成主片 .subset.woff2 并重写 fonts.css。

主片字符集 = ASCII 可打印 + GB2312 符号区(A1-A9) + 一级常用汉字(B0-D7)
           + 前端源码中实际出现的全部非 ASCII 字符（保证界面文案永不触发兜底片）。
原始全量文件保留为兜底片，靠 unicode-range 只在生僻字出现时按需下载。

用法（需先 ./venv/bin/pip install fonttools brotli）:
    ./venv/bin/python scripts/subset_fonts_cjk.py
"""

from pathlib import Path

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

REPO_ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = REPO_ROOT / "frontend" / "src" / "assets" / "fonts"
CSS_PATH = REPO_ROOT / "frontend" / "src" / "styles" / "fonts.css"
APP_SRC = REPO_ROOT / "frontend" / "src"
APP_INDEX = REPO_ROOT / "frontend" / "index.html"
WEIGHTS: dict[str, int] = {"NotoSansSC-Regular": 400, "NotoSansSC-Medium": 500}

CSS_HEADER = """\
/* ===== Source Han Sans SC 分片加载 =====
   主片(.subset)=GB2312 一级常用汉字+符号区+ASCII+界面实际用字，首屏只下主片；
   全量原文件做兜底片，仅当出现主片未覆盖的生僻字时按 unicode-range 按需下载。
   同族同字重规则重叠时后声明者优先，故兜底片在前、主片在后。
   兜底片也带 unicode-range(=字体实际 cmap)，避免字体本就没有的字符(如 emoji)
   触发全量文件的无谓下载。由 scripts/subset_fonts_cjk.py 生成，勿手改。 */
"""


def gb2312_common_charset() -> set[int]:
    """ASCII 可打印 + GB2312 符号区 + 一级汉字。"""
    chars: set[int] = set(range(0x20, 0x7F))
    for hi in [*range(0xA1, 0xAA), *range(0xB0, 0xD8)]:
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(ord(bytes([hi, lo]).decode("gb2312")))
            except UnicodeDecodeError:
                continue
    return chars


def app_used_charset() -> set[int]:
    """前端源码里出现过的全部非 ASCII 字符。"""
    chars: set[int] = set()
    files = [APP_INDEX] + [
        p
        for p in APP_SRC.rglob("*")
        if p.is_file() and p.suffix in {".tsx", ".ts", ".css", ".html", ".json"}
    ]
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        chars.update(ord(ch) for ch in text if ord(ch) > 0x7F)
    return chars


def compact_ranges(codepoints: set[int]) -> str:
    """把码点集合压成 CSS unicode-range 串。"""
    pts = sorted(codepoints)
    ranges: list[str] = []
    start = prev = pts[0]
    for cp in pts[1:]:
        if cp == prev + 1:
            prev = cp
            continue
        ranges.append(f"U+{start:X}" if start == prev else f"U+{start:X}-{prev:X}")
        start = prev = cp
    ranges.append(f"U+{start:X}" if start == prev else f"U+{start:X}-{prev:X}")
    return ",".join(ranges)


def subset_font(name: str, charset: set[int]) -> Path:
    src = FONTS_DIR / f"{name}.woff2"
    dst = FONTS_DIR / f"{name}.subset.woff2"
    font = TTFont(str(src))
    options = Options()
    options.flavor = "woff2"
    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=sorted(charset))
    subsetter.subset(font)
    font.save(str(dst))
    print(f"{name}: {src.stat().st_size // 1024}K -> {dst.stat().st_size // 1024}K")
    return dst


def cmap_ranges(font_file: Path) -> str:
    return compact_ranges(set(TTFont(str(font_file)).getBestCmap().keys()))


def face(family: str, src: str, weight: int, unicode_range: str | None) -> str:
    lines = [
        "@font-face {",
        f'  font-family: "{family}";',
        f'  src: url("../assets/fonts/{src}") format("woff2");',
        "  font-style: normal;",
        f"  font-weight: {weight};",
        "  font-display: swap;",
    ]
    if unicode_range:
        lines.append(f"  unicode-range: {unicode_range};")
    lines.append("}")
    return "\n".join(lines)


def write_css() -> None:
    parts = [CSS_HEADER]
    for name, weight in WEIGHTS.items():
        ranges = cmap_ranges(FONTS_DIR / f"{name}.woff2")
        parts.append(face("Source Han Sans SC", f"{name}.woff2", weight, ranges))
        parts.append("")
    for name, weight in WEIGHTS.items():
        ranges = cmap_ranges(FONTS_DIR / f"{name}.subset.woff2")
        parts.append(face("Source Han Sans SC", f"{name}.subset.woff2", weight, ranges))
        parts.append("")
    for name, weight in (("Inter-Regular", 400), ("Inter-Medium", 500)):
        parts.append(face("Inter", f"{name}.woff2", weight, None))
        parts.append("")
    CSS_PATH.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {CSS_PATH} ({CSS_PATH.stat().st_size // 1024}K)")


def main() -> None:
    charset = gb2312_common_charset() | app_used_charset()
    print(f"charset size: {len(charset)}")
    for name in WEIGHTS:
        subset_font(name, charset)
    write_css()


if __name__ == "__main__":
    main()
