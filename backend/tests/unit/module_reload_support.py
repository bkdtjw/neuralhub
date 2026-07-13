from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest

# setitem 占位对象：只为让 monkeypatch 记下"该键原本不存在"，登记后随即删除。
_ABSENT = ModuleType("_fresh_import_absent")


def fresh_import(monkeypatch: pytest.MonkeyPatch, *names: str) -> tuple[ModuleType, ...]:
    """重导 names 各模块并按序返回新模块对象；原 sys.modules 条目在测试结束时还原。

    直接 ``sys.modules.pop()`` 后重导会永久留下新模块副本，其中的异常类/模型类
    是新类对象：先前已 import 的模块仍持旧类，之后才首次 import 的代码（如按
    开关懒注册的 API 路由）绑到新类，``except``/``isinstance`` 因类身份不一致
    而失效（曾令 test_x_api 的 502 用例仅在全量顺序下穿透路由捕获）。改由
    monkeypatch 托管：undo 时旧模块对象原样放回，原本不存在的条目则删除。
    """
    for name in names:
        if name in sys.modules:
            monkeypatch.delitem(sys.modules, name)
        else:
            monkeypatch.setitem(sys.modules, name, _ABSENT)
            del sys.modules[name]
        # 子模块 import 还会绑到父包属性（backend.common.x_budget → backend.common
        # 的 x_budget 属性），而 monkeypatch 的字符串路径补丁沿 getattr 链解析——
        # 父包属性不还原，后续补丁会打到重导残留的"死"模块上。一并登记还原。
        parent_name, _, attr = name.rpartition(".")
        parent = sys.modules.get(parent_name) if parent_name else None
        if parent is not None:
            monkeypatch.setattr(parent, attr, getattr(parent, attr, _ABSENT), raising=False)
    return tuple(importlib.import_module(name) for name in names)


__all__ = ["fresh_import"]
