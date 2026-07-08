from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from backend.core.s04_sub_agents import is_readonly_blocked


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存逻辑单测，跳过 PostgresContainer 避免拖慢。
    yield


# 白名单化后应拦截的写/删/执行命令（含多段、命令替换、重定向、wrapper 绕过）。
BLOCKED_COMMANDS = [
    "touch a",
    "dd if=x of=y",
    "curl -o f url",
    "wget -O f url",
    "find . -delete",
    "find . -exec rm {} ;",
    "truncate -s0 f",
    "ln -s a b",
    "rsync a b",
    "tar -xf a",
    "unzip a",
    "git apply p",
    "git commit -m x",
    "pip install x",
    "ls; touch x",
    "cat f | touch x",
    "ls && rm f",
    "echo $(touch x)",
    "echo `touch x`",
    "sudo touch x",
    "python -c 'print(1)'",
    "cat a > b",
    "cat a >> b",
    "sed -i s/a/b/ f",
    "sort -o out f",
    "awk 'BEGIN{system(\"touch x\")}'",
]


@pytest.mark.parametrize("command", BLOCKED_COMMANDS)
def test_readonly_blocks_write_commands(command: str) -> None:
    assert is_readonly_blocked(command) is True


# 只读检查命令应放行（含 git 只读子命令、find 只读用法、wrapper、算术展开、管道）。
ALLOWED_COMMANDS = [
    "ls -la",
    "cat f",
    "grep x f",
    "rg x",
    "find . -name '*.py'",
    "git status",
    "git log",
    "git diff",
    "head f",
    "tail f",
    "wc f",
    "stat f",
    "diff a b",
    "sed 's/a/b/' f",
    "env FOO=1 cat f",
    "echo $((1+1))",
    "cat f | grep x",
]


@pytest.mark.parametrize("command", ALLOWED_COMMANDS)
def test_readonly_allows_read_commands(command: str) -> None:
    assert is_readonly_blocked(command) is False


def test_empty_command_is_blocked() -> None:
    assert is_readonly_blocked("") is True
    assert is_readonly_blocked("   ") is True
