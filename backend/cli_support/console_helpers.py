from __future__ import annotations

from backend.common.types import ProviderConfig

from .display import CliPrinter

HELP_TEXT = """可用命令:
  /help                 显示帮助
  /clear                清空对话历史
  /provider             列出 provider
  /provider <name>      切换 provider
  /model <name>         切换模型
  /workspace <path>     切换工作目录
  /tools                显示当前工具列表
  /tasks                显示定时任务列表
  /tasks run <id>       立即执行指定任务
  /plan <message>       Plan & Execute 模式执行任务
  /plan show <name>     查看某个计划详情
  /plans                列出历史计划
  /exit                 退出"""


def _read_multiline_input(printer: CliPrinter) -> str | None:
    lines: list[str] = []
    while True:
        try:
            line = input(printer.prompt(multiline=bool(lines)))
        except EOFError:
            return None
        except KeyboardInterrupt:
            print("\n[input] 已取消当前输入。")
            return ""
        if not lines and not line.strip():
            return ""
        lines.append(line[:-1] if line.endswith("\\") else line)
        if line.endswith("\\"):
            continue
        return "\n".join(lines).strip()


def _find_provider(providers: list[ProviderConfig], target: str) -> ProviderConfig | None:
    needle = target.strip().lower()
    return next(
        (item for item in providers if needle in {item.id.lower(), item.name.lower()}),
        None,
    )


def _find_model_owner(providers: list[ProviderConfig], model: str) -> ProviderConfig | None:
    return next((item for item in providers if model in item.available_models), None)


def _format_provider_lines(providers: list[ProviderConfig], current_id: str) -> str:
    lines = ["[info] 当前 provider 列表:"]
    for provider in providers:
        lines.append(
            f"{'*' if provider.id == current_id else '-'} "
            f"{provider.name} [{provider.id}] -> {provider.default_model}"
            f"{' (default)' if provider.is_default else ''}"
        )
    return "\n".join(lines)


__all__ = [
    "HELP_TEXT",
    "_find_model_owner",
    "_find_provider",
    "_format_provider_lines",
    "_read_multiline_input",
]
