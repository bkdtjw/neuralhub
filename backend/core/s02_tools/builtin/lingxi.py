"""灵犀金融数据Skills适配器 - 通过Node.js调用国泰海通金融数据接口"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

# 灵犀Skills基础路径
LINGXI_SKILLS_BASE = Path(__file__).parent.parent.parent.parent.parent.parent / "skills"
LINGXI_SHARED_PATH = LINGXI_SKILLS_BASE / "gtht-skill-shared" / "gtht-entry.json"


def _check_auth() -> bool:
    """检查是否已授权"""
    return LINGXI_SHARED_PATH.exists()


def _decode_output(data: bytes) -> str:
    """解码输出"""
    if not data:
        return ""
    for encoding in ("utf-8", "gbk", "cp936", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


async def _call_lingxi_skill(
    skill_dir: str,
    gateway: str,
    tool_name: str,
    params: dict[str, str],
    timeout: int = 30,
) -> ToolResult:
    """调用灵犀Skill

    Args:
        skill_dir: Skill目录名（如 lingxi-financialsearch-skill）
        gateway: 网关名（如 financial）
        tool_name: 工具名（如 financial-search）
        params: 参数字典
        timeout: 超时时间（秒）
    """
    # 检查授权
    if not _check_auth():
        return ToolResult(
            output="灵犀Skills尚未授权，请先执行授权流程："
            f"cd {LINGXI_SKILLS_BASE / skill_dir} && node skill-entry.js authChecker auth --channel",
            is_error=True,
        )

    skill_path = LINGXI_SKILLS_BASE / skill_dir
    if not skill_path.exists():
        return ToolResult(output=f"Skill目录不存在: {skill_path}", is_error=True)

    entry_file = skill_path / "skill-entry.js"
    if not entry_file.exists():
        return ToolResult(output=f"Skill入口文件不存在: {entry_file}", is_error=True)

    # 构建命令
    args_list = [f"{k}={v}" for k, v in params.items()]
    cmd_parts = ["node", "skill-entry.js", "mcpClient", "call", gateway, tool_name] + args_list
    cmd = " ".join(cmd_parts)

    try:
        process = await asyncio.create_subprocess_exec(
            "node",
            "skill-entry.js",
            "mcpClient",
            "call",
            gateway,
            tool_name,
            *(f"{k}={v}" for k, v in params.items()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(skill_path),
        )

        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        if process.returncode != 0:
            stderr_text = _decode_output(stderr).strip()
            return ToolResult(
                output=f"命令执行失败 (退出码: {process.returncode}): {stderr_text or _decode_output(stdout)}",
                is_error=True,
            )

        output = _decode_output(stdout).strip()

        # 尝试解析JSON输出
        try:
            result = json.loads(output)
            if isinstance(result, dict) and "text" in result:
                return ToolResult(output=result["text"])
            return ToolResult(output=output)
        except json.JSONDecodeError:
            return ToolResult(output=output)

    except asyncio.TimeoutError:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        return ToolResult(output=f"命令执行超时 (超过 {timeout} 秒)", is_error=True)
    except FileNotFoundError:
        return ToolResult(
            output="未找到 Node.js，请确保已安装 Node.js 并在 PATH 中",
            is_error=True,
        )
    except Exception as exc:
        return ToolResult(output=f"执行出错: {exc!s}", is_error=True)


def create_lingxi_financial_search_tool() -> tuple[ToolDefinition, ToolExecuteFn]:
    """创建灵犀金融数据查询工具"""
    definition = ToolDefinition(
        name="lingxi_financial_search",
        description="国泰海通金融数据查询：通过自然语言查询A股实时行情、公司基本信息、F10财务数据、个股技术指标等金融数据。"
        "支持查询营业收入、净利润、市值、市盈率、市净率、换手率、成交量等指标。"
        "可批量查询多只股票的多个指标。"
        "注意：调用后需在答案末尾添加免责声明。",
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "query": {
                    "type": "string",
                    "description": "自然语言查询，如'科大讯飞营业收入'、'贵州茅台净利润和市值'、'A股涨幅榜前10'",
                },
            },
            required=["query"],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(output="缺少查询参数", is_error=True)

        result = await _call_lingxi_skill(
            skill_dir="lingxi-financialsearch-skill",
            gateway="financial",
            tool_name="financial-search",
            params={"query": query},
        )

        # 添加免责声明
        if not result.is_error:
            disclaimer = (
                "\n\n"
                "以上信息源自第三方数据整理，仅供参考。"
                "本Skill仅提供客观数据，调用本Skill后生成的内容，不构成投资建议。"
            )
            result.output = result.output + disclaimer

        return result

    return definition, execute


def create_lingxi_realtime_marketdata_tool() -> tuple[ToolDefinition, ToolExecuteFn]:
    """创建灵犀实时行情工具"""
    definition = ToolDefinition(
        name="lingxi_realtime_marketdata",
        description="国泰海通实时行情查询：查询A股、港股、美股、ETF与指数的实时行情。"
        "支持单只或多只标的的实时行情，数据包括最新价、涨跌幅、涨跌额、成交量、成交额、换手率、资金净流入、量比等。"
        "当用户询问股价、涨跌幅、行情走势、资金流向时使用。"
        "注意：调用后需在答案末尾添加免责声明。",
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "query": {
                    "type": "string",
                    "description": "自然语言查询，如'宁德时代最新价'、'比亚迪涨跌幅'、'茅台成交量'",
                },
            },
            required=["query"],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(output="缺少查询参数", is_error=True)

        result = await _call_lingxi_skill(
            skill_dir="lingxi-realtimemarketdata-skill",
            gateway="realtime",
            tool_name="realtime-marketdata",
            params={"query": query},
        )

        # 添加免责声明
        if not result.is_error:
            disclaimer = (
                "\n\n"
                "本Skill仅提供客观数据，调用本Skill后生成的内容，不构成投资建议。"
            )
            result.output = result.output + disclaimer

        return result

    return definition, execute


def create_lingxi_ranklist_tool() -> tuple[ToolDefinition, ToolExecuteFn]:
    """创建灵犀市场榜单工具"""
    definition = ToolDefinition(
        name="lingxi_ranklist",
        description="国泰海通市场榜单查询：查询涨跌幅、成交额、成交量、换手率、资金净流入等市场排行榜。"
        "支持各种维度的股票排名，如涨幅榜、跌幅榜、成交额排行等。"
        "当用户查询市场榜单、排行榜时使用。",
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "query": {
                    "type": "string",
                    "description": "自然语言查询，如'涨幅榜前10'、'成交额排名'、'换手率榜前20'",
                },
            },
            required=["query"],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(output="缺少查询参数", is_error=True)

        # 根据查询内容解析参数
        params = {"query": query}

        # 尝试解析更具体的参数
        query_lower = query.lower()
        if "前" in query or "top" in query_lower:
            # 尝试提取数字
            import re

            match = re.search(r"(\d+)", query)
            if match:
                params["limit"] = match.group(1)

        return await _call_lingxi_skill(
            skill_dir="lingxi-ranklist-skill",
            gateway="ranklist",
            tool_name="ranklist",
            params=params,
        )

    return definition, execute


def create_lingxi_smart_stock_selection_tool() -> tuple[ToolDefinition, ToolExecuteFn]:
    """创建灵犀智能选股工具"""
    definition = ToolDefinition(
        name="lingxi_smart_stock_selection",
        description="国泰海通智能选股：通过自然语言进行多指标选股，对选股结果进行历史回测。"
        "支持根据财务指标、技术指标等条件筛选股票，并进行回测分析。"
        "当用户需要进行选股或回测时使用。"
        "注意：调用回测后需在答案末尾添加免责声明。",
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "query": {
                    "type": "string",
                    "description": "自然语言选股条件，如'选出市盈率小于20且营收增长超过10%的股票'、"
                    "'回测市值前50股票近一年表现'",
                },
            },
            required=["query"],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(output="缺少查询参数", is_error=True)

        result = await _call_lingxi_skill(
            skill_dir="lingxi-smartstockselection-skill",
            gateway="smartstock",
            tool_name="smart-stock-selection",
            params={"query": query},
        )

        # 如果是回测，添加免责声明
        if not result.is_error and "回测" in query:
            disclaimer = (
                "\n\n"
                "以上展示模拟历史回测结果仅供参考，不代表未来收益，不构成任何投资建议、"
                "投资分析意见或收益承诺。本Skill仅提供客观数据，调用本Skill后生成的内容，不构成投资建议。"
            )
            result.output = result.output + disclaimer
        elif not result.is_error:
            disclaimer = (
                "\n\n"
                "以上信息源自第三方数据整理，仅供参考。"
                "本Skill仅提供客观数据，调用本Skill后生成的内容，不构成投资建议。"
            )
            result.output = result.output + disclaimer

        return result

    return definition, execute


__all__ = [
    "create_lingxi_financial_search_tool",
    "create_lingxi_realtime_marketdata_tool",
    "create_lingxi_ranklist_tool",
    "create_lingxi_smart_stock_selection_tool",
]
