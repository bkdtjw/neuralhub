from __future__ import annotations

import importlib
import sys

import pytest

from backend.tests.unit.module_reload_support import fresh_import

# 选一个导入无副作用的小模块作重导标的即可，行为与被测模块无关。
_TARGET = "backend.common.x_budget"


def test_fresh_import_returns_new_module_then_restores_original() -> None:
    original = importlib.import_module(_TARGET)
    with pytest.MonkeyPatch.context() as mp:
        (fresh,) = fresh_import(mp, _TARGET)
        assert fresh is not original
        assert sys.modules[_TARGET] is fresh
        assert fresh.XBudgetError is not original.XBudgetError  # 新类对象，非同一身份
    # undo 后旧模块对象原样放回——后续用例的 except/isinstance 不受重导影响
    assert sys.modules[_TARGET] is original


def test_fresh_import_restores_parent_package_attribute() -> None:
    import backend.common as common_pkg

    original = importlib.import_module(_TARGET)
    with pytest.MonkeyPatch.context() as mp:
        (fresh,) = fresh_import(mp, _TARGET)
        assert common_pkg.x_budget is fresh  # 测试期间父包属性同步指向新模块
    # 还原后父包属性回到原模块——monkeypatch 字符串路径补丁沿 getattr 链解析，
    # 此处不还原的话，后续用例的补丁会打到重导残留的"死"模块上（曾令
    # test_x_search_service 的降级用例在全量顺序下命中真实闸门被限速）。
    assert common_pkg.x_budget is original


def test_fresh_import_removes_entry_absent_beforehand(monkeypatch: pytest.MonkeyPatch) -> None:
    importlib.import_module(_TARGET)
    monkeypatch.delitem(sys.modules, _TARGET)  # 模拟"此前从未 import"；用例结束由外层还原
    with pytest.MonkeyPatch.context() as mp:
        (fresh,) = fresh_import(mp, _TARGET)
        assert sys.modules[_TARGET] is fresh
    # undo 后不残留任何条目，恢复"未导入"原状
    assert _TARGET not in sys.modules
