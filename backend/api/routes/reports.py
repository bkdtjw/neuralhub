"""Markdown report rendering route.

Renders saved .md reports as styled HTML pages for browser viewing.
No authentication required — reports are public read-only.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown as md_lib
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["reports"])

_REPORTS_DIR = Path(os.getcwd()) / "reports"
_PLAN_REPORTS_DIR = Path(os.getcwd()) / "data" / "plans"
_BEIJING = ZoneInfo("Asia/Shanghai")

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "SF Pro Text", "Segoe UI", Roboto,
      "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f0f2f5; color: #1a1a1a; line-height: 1.8; min-height: 100vh;
  }}
  .container {{ max-width: 780px; margin: 0 auto; padding: 2rem 1rem; }}
  .header {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff; padding: 2rem 2.5rem; border-radius: 16px;
    margin-bottom: 1.5rem; box-shadow: 0 4px 20px rgba(102,126,234,0.25);
  }}
  .header h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 0.25rem; }}
  .header .subtitle {{ opacity: 0.85; font-size: 0.9rem; }}
  .card {{
    background: #fff; border-radius: 12px; padding: 2rem 2.5rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06); margin-bottom: 1rem;
  }}
  .meta-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem; margin-bottom: 1.5rem;
  }}
  .meta-item {{ padding: 0.75rem 1rem; background: #f8f9fb; border-radius: 8px; }}
  .meta-item .label {{ font-size: 0.75rem; color: #8c8c8c;
    text-transform: uppercase; letter-spacing: 0.5px; }}
  .meta-item .value {{ font-size: 0.95rem; font-weight: 500; margin-top: 0.2rem; }}
  .status-badge {{
    display: inline-block; padding: 0.2rem 0.75rem; border-radius: 20px;
    font-size: 0.8rem; font-weight: 500;
  }}
  .status-success {{ background: #e6f7ed; color: #1a7d3f; }}
  .status-error {{ background: #fde8e8; color: #c5221f; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; color: #1a1a1a; margin-bottom: 0.75rem; }}
  h2 {{ font-size: 1.15rem; font-weight: 600; color: #333; margin: 1.5rem 0 0.5rem; }}
  h3 {{ font-size: 1rem; font-weight: 600; color: #444; margin: 1rem 0 0.4rem; }}
  p {{ margin: 0.5rem 0; color: #333; }}
  strong {{ color: #1a1a1a; }}
  ul, ol {{ margin: 0.5rem 0; padding-left: 1.5rem; }}
  li {{ margin: 0.25rem 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }}
  th {{ background: #f8f9fb; color: #555; font-weight: 600; text-align: left;
       padding: 0.6rem 0.8rem; border-bottom: 2px solid #e8e8e8; }}
  td {{ padding: 0.6rem 0.8rem; border-bottom: 1px solid #f0f0f0; }}
  tr:hover td {{ background: #fafbfc; }}
  code {{ background: #f1f3f5; padding: 0.15rem 0.45rem; border-radius: 4px;
          font-size: 0.88em; color: #d63384;
          font-family: "SF Mono", "Fira Code", Menlo, monospace; }}
  pre {{
    background: #1e1e2e; color: #cdd6f4; padding: 1.25rem 1.5rem; border-radius: 10px;
    overflow-x: auto; margin: 1rem 0; font-size: 0.85rem; line-height: 1.6;
  }}
  pre code {{ background: none; color: inherit; padding: 0; }}
  blockquote {{
    border-left: 4px solid #667eea; background: #f8f9ff; margin: 1rem 0;
    padding: 0.75rem 1.25rem; border-radius: 0 8px 8px 0; color: #444;
  }}
  hr {{ border: none; height: 1px; background: #e8e8e8; margin: 1.5rem 0; }}
  .footer {{
    text-align: center; color: #aaa; font-size: 0.75rem; margin-top: 2rem; padding-bottom: 1rem;
  }}
  @media (max-width: 600px) {{
    .container {{ padding: 1rem 0.5rem; }}
    .header, .card {{ padding: 1.25rem; border-radius: 10px; }}
    .meta-grid {{ grid-template-columns: 1fr 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">
{body}
<div class="footer">Agent Studio · {generated_at}</div>
</div>
</body>
</html>"""


@router.get("/reports/plans/{filepath:path}", response_class=HTMLResponse)
async def render_plan_report(filepath: str) -> HTMLResponse:
    """Render a saved Plan markdown report."""
    return _render_markdown_report(_PLAN_REPORTS_DIR, filepath)


@router.get("/reports/{filepath:path}", response_class=HTMLResponse)
async def render_report(filepath: str) -> HTMLResponse:
    """Render a markdown report file as a styled HTML page."""
    return _render_markdown_report(_REPORTS_DIR, filepath)


def _render_markdown_report(root: Path, filepath: str) -> HTMLResponse:
    # Security: prevent path traversal
    if ".." in filepath or filepath.startswith("/"):
        return HTMLResponse(
            _error_page("400 Bad Request", "Invalid path."), status_code=400,
        )

    target = (root / filepath).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return HTMLResponse(
            _error_page("403 Forbidden", "Access denied."), status_code=403,
        )

    if not target.is_file():
        return HTMLResponse(
            _error_page("404 Not Found", "Report not found."), status_code=404,
        )

    text = target.read_text(encoding="utf-8")
    extensions: list[str] = ["tables", "fenced_code"]
    try:
        extensions.append("codehilite")
    except Exception:
        pass
    body = md_lib.markdown(text, extensions=extensions)
    # Wrap content sections in card divs for visual grouping
    body = body.replace("<hr>", '</div><div class="card">')
    body = f'<div class="card">{body}</div>'
    title = target.stem
    generated_at = datetime.now(_BEIJING).strftime("%Y-%m-%d %H:%M")
    html = _HTML_TEMPLATE.format(title=title, body=body, generated_at=generated_at)
    return HTMLResponse(content=html)


def _error_page(title: str, message: str) -> str:
    return _HTML_TEMPLATE.format(
        title=title,
        body=f'<div class="card" style="text-align:center;padding:3rem;">'
             f'<h2>{title}</h2><p style="color:#888;margin-top:0.5rem;">{message}</p></div>',
        generated_at=datetime.now(_BEIJING).strftime("%Y-%m-%d %H:%M"),
    )
