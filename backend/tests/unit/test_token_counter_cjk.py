from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from backend.core.s06_context_compression.level1_artifact import token_count
from backend.core.s06_context_compression.token_counter import (
    TokenCounter,
    estimate_tokens,
)


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


def test_pure_cjk_estimate_far_exceeds_len_div_four() -> None:
    text = "汉" * 100
    naive = len(text) // 4  # 旧口径严重低估：仅 25
    estimated = estimate_tokens(text)
    assert naive == 25
    assert estimated == 100  # CJK 每字 1 token
    assert estimated >= 90


def test_pure_ascii_estimate_matches_len_div_four() -> None:
    text = "the quick brown fox jumps over the lazy dog " * 5
    assert estimate_tokens(text) == len(text) // 4


def test_mixed_estimate_between_ascii_and_cjk() -> None:
    text = "汉字" * 25 + "abcd" * 25  # 50 个 CJK + 100 个 ASCII
    ascii_floor = estimate_tokens("a" * len(text))  # 纯 ASCII 下界
    cjk_ceiling = estimate_tokens("汉" * len(text))  # 纯 CJK 上界
    estimated = estimate_tokens(text)
    assert ascii_floor < estimated < cjk_ceiling
    assert estimated == 75  # 50(CJK) + 100//4(ASCII) = 75


def test_cjk_ranges_each_count_as_one_token() -> None:
    # 覆盖工作项列出的各 Unicode 区间，均应按 1 token/字计。
    samples = {
        "cjk_ideograph": "语",  # U+8BED CJK 基本区
        "cjk_ext_a": "㐀",  # U+3400 扩展 A
        "cjk_compat": "豈",  # U+F900 兼容表意文字
        "hiragana": "あ",  # U+3042 平假名
        "katakana": "カ",  # U+30AB 片假名
        "hangul": "가",  # U+AC00 谚文
        "fullwidth": "Ａ",  # U+FF21 全角
    }
    for label, char in samples.items():
        assert estimate_tokens(char * 10) == 10, label


def test_token_count_shares_weighting_and_keeps_floor() -> None:
    # level1_artifact.token_count 与 estimate_tokens 同口径，且保留原有下限语义。
    assert token_count("") == 0  # 空串仍为 0
    assert token_count("ab") == 1  # estimate=0 → 非空至少计 1
    assert token_count("汉") == 1  # estimate=1
    cjk = "工具结果" * 50  # 200 个 CJK
    assert token_count(cjk) == estimate_tokens(cjk) == 200


def test_counter_delegates_to_shared_estimate() -> None:
    # TokenCounter 内部私有估算与公共 estimate_tokens 保持一致。
    assert TokenCounter._estimate_text_tokens("混合 mixed 文本 text") == estimate_tokens(
        "混合 mixed 文本 text"
    )
