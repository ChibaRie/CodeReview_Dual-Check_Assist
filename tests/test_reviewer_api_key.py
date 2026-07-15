"""Reviewer.review 线程化 api_key —— TDD 单元测试。

Verifies that ``Reviewer.review`` accepts an optional ``api_key`` argument
and forwards it to ``FallbackChain.call``.
"""
from unittest.mock import MagicMock, patch

from circuit_breaker import BreakerPool, CircuitBreaker
from reviewer import Reviewer


def _make_fresh_pool() -> BreakerPool:
    """构造一个 CLOSED 状态的 python 熔断池，避免被持久化文件污染。"""
    pool = BreakerPool.__new__(BreakerPool)
    pool._pool = {"python": CircuitBreaker(threshold=3, cooldown=60)}
    pool._persist_path = ""
    return pool


def _patch_prepare(rev: Reviewer):
    """Patch _prepare 返回 (config, cache_dir, persist_path, pool)。
    config 仅给出空 models 列表（FallbackChain 已被 mock）。
    """
    cfg = {"cache": {}, "review": {}, "models": []}
    pool = _make_fresh_pool()
    rev._breaker_pool = pool
    return patch.object(
        rev, "_prepare", return_value=(cfg, "data/.cache", "", pool)
    )


def test_reviewer_review_accepts_api_key():
    """review(api_key=...) 经由 _run_ai 传到 FallbackChain.call(api_key=...)。"""
    rev = Reviewer()

    mock_chain_result = MagicMock()
    mock_chain_result.text = '{"confirmation": [], "rejection": [], "new_findings": []}'
    mock_chain_result.tier = "deepseek"

    with _patch_prepare(rev), patch("reviewer.FallbackChain") as MockChain:
        MockChain.return_value.call.return_value = mock_chain_result
        report, perf = rev.review("x = 1\n", "python", api_key="sk-test", use_cache=False)

        # 验证 FallbackChain.call 被调用时传入了 api_key
        call_kwargs = MockChain.return_value.call.call_args[1]
        assert call_kwargs.get("api_key") == "sk-test"
        assert perf["ai_tier"] == "deepseek"


def test_reviewer_review_default_api_key_empty():
    """不传 api_key 时，FallbackChain.call 仍被调用（api_key 默认空串，向后兼容）。"""
    rev = Reviewer()

    mock_chain_result = MagicMock()
    mock_chain_result.text = '{"confirmation": [], "rejection": [], "new_findings": []}'
    mock_chain_result.tier = "local_fallback"

    with _patch_prepare(rev), patch("reviewer.FallbackChain") as MockChain:
        MockChain.return_value.call.return_value = mock_chain_result
        report, perf = rev.review("y = 2\n", "python", use_cache=False)

        call_kwargs = MockChain.return_value.call.call_args[1]
        assert call_kwargs.get("api_key", "UNSET") == ""

    # 静态无问题 + AI tier local_fallback → 风险等级 "可合并"
    assert report.risk in ("可合并", "修复后合并")


def test_api_key_not_logged_or_persisted():
    """api_key 不出现在 risk/summary/findings 等 report 字段中。"""
    rev = Reviewer()
    mock_chain_result = MagicMock()
    mock_chain_result.text = '{"confirmation": [], "rejection": [], "new_findings": []}'
    mock_chain_result.tier = "deepseek"

    with _patch_prepare(rev), patch("reviewer.FallbackChain") as MockChain:
        MockChain.return_value.call.return_value = mock_chain_result
        report, perf = rev.review("z = 3\n", "python", api_key="sk-secret-do-not-leak",
                                  use_cache=False)

    serialized = repr(report.__dict__) + repr(perf)
    assert "sk-secret-do-not-leak" not in serialized


def test_review_uses_cache_path_still_works_with_api_key():
    """传入 api_key 且启用 cache 命中时直接返回，_run_ai 不被调用。"""
    rev = Reviewer()
    # 预填 cache：通过 _read_cache 返回伪造报告
    from app import FinalReport
    cached_report = FinalReport(
        risk="可合并",
        summary="cached",
        static_summary="ok",
        ai_summary="cached-ai",
        findings=[],
    )
    with _patch_prepare(rev), patch("reviewer.CQRSRouter") as MockRouter, \
         patch("reviewer.FallbackChain") as MockChain:
        MockRouter.return_value.try_read.return_value = cached_report.__dict__
        MockChain.return_value.call.return_value = MagicMock(text="{}", tier="deepseek")
        report, perf = rev.review("cached = 1\n", "python", api_key="sk-cache", use_cache=True)
        assert perf["cache_hit"] is True
        # 缓存命中 _run_ai 不被调，FallbackChain.call 也不被调
        assert MockChain.return_value.call.call_count == 0