from __future__ import annotations

from typing import Any

from .plan_control_store import PlanControlStore


def apply_control_signal(runner: Any) -> None:
    """读取持久化控制信号并应用到 runner，应用后立即清除信号文件。

    stop / pause / resume 均为一次性命令：一旦被消费即删除信号文件，
    避免同 session 的后续执行 / 恢复被旧信号污染（例如新一轮循环开局即被误判为 stop / pause）。
    """
    store = PlanControlStore()
    signal = store.read(runner._session_id)
    if signal.action == "stop":
        runner.cancel()
    elif signal.action == "pause":
        runner._control.request_pause()
    elif signal.action == "resume":
        runner._control.resume(signal.instruction)
    else:
        return
    store.clear(runner._session_id)


def clear_control_signal(session_id: str) -> None:
    """清除遗留控制信号，保证每次新执行 / 恢复从干净状态开始。"""
    PlanControlStore().clear(session_id)


__all__ = ["apply_control_signal", "clear_control_signal"]
