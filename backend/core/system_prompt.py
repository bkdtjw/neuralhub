from __future__ import annotations

import platform

COMPRESSION_RETENTION_TEMPLATE = """
压缩时按以下优先级保留信息：
P1 绝不删：标识符（商品ID、短链URL、淘口令、item_id、shop_id、订单号）
P2 绝不删：用户决策（选了什么、排除了什么、为什么）
P3 保留结论：失败路径（什么失败了、原因、换了什么策略）
P4 保留摘要：关键结果（top 3 名称+价格，不需要完整 JSON）
P5 可删但存文件：工具原始输出（写入文件，保留路径）
P6 可删：日常寒暄、确认语句
标识符必须原样保留，不得修改任何字符。
当摘要或工具结果只给出文件路径且信息不足时，调用 read_history 回查原文。
""".strip()


def build_system_prompt(workspace: str | None = None) -> str:
    os_name = platform.system()
    if os_name == "Windows":
        shell_info = (
            "cmd.exe。使用 dir（不要用 ls）、type（不要用 cat）、cd、findstr "
            "等 Windows 命令。"
        )
        command_rule = (
            "绝对不要使用 Linux 命令（pwd、ls、cat、grep），只用 Windows 命令"
            "（dir、type、cd、findstr）。"
        )
    else:
        shell_info = "bash。使用 ls、cat、cd、grep 等 Unix 命令。"
        command_rule = "优先使用当前系统原生命令，不要混用其他操作系统的命令。"

    parts = [
        f"你是一个编程助手。当前操作系统: {os_name}。",
        f"执行 shell 命令时使用 {shell_info}",
        command_rule,
        "如果工具调用失败，必须先阅读错误输出，再决定是否调整命令。",
        "不要原样重复同一个失败命令；只有在参数、路径或策略发生变化时才允许重试，并说明为什么要重试。",
        (
            "如果连续 3 次工具调用失败，停止继续调用工具，直接向用户解释失败"
            "原因、当前限制和下一步建议。"
        ),
    ]
    if workspace:
        parts.append(f"当前工作目录: {workspace}")
    parts.extend(
        [
            "你有 spawn_agent 工具可以派生子 agent 并行执行任务。",
            "多个子任务互不依赖、可以同时进行时，用 spawn_agent 一次传多个任务并行执行。",
            "子任务之间有先后依赖，或任务简单到你自己几步就能完成时，不要派子 agent。",
            "子 agent 执行完成后你会收到全部结果，请汇总后再回复用户。",
        ]
    )
    parts.append("回复使用中文。")
    parts.append(COMPRESSION_RETENTION_TEMPLATE)
    return "\n".join(part for part in parts if part)


__all__ = ["COMPRESSION_RETENTION_TEMPLATE", "build_system_prompt"]
