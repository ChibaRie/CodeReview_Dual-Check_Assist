"""Reviewer 构造（惰性建池）+ app.review↔Reviewer.review parity。"""
from unittest.mock import patch

import app
from reviewer import Reviewer


class TestReviewerConstruction:
    def test_init_no_breaker_pool(self):
        """默认构造不预建 pool（惰性）。"""
        rev = Reviewer()
        assert rev._breaker_pool is None

    def test_prepare_lazy_builds_pool(self):
        """_prepare 建池：惰性首建后 _breaker_pool 非空（复刻旧 _breaker_pool quirk）。
        直接调 _prepare 验建池副作用，不走 full review() 避免网络。"""
        rev = Reviewer()
        rev._prepare("")
        assert rev._breaker_pool is not None


class TestReviewForwardingParity:
    def test_forwarding_parity_risk_and_findings(self):
        """app.review 与 Reviewer.review 在相同输入/mock 下 risk 一致 + findings 数一致。
        Inline mock urllib.request.urlopen（不动 conftest）。"""
        sample = b'{"confirmation": [], "rejection": [], "new_findings": []}'
        fake_resp = type(
            "R", (), {
                "read": lambda self: sample,
                "status": 200,
                "__enter__": lambda s: s,
                "__exit__": lambda s, *a: None,
            }
        )()
        code = "def f(a=[]):\n    pass\n"
        with patch("urllib.request.urlopen", return_value=fake_resp):
            r_app, _ = app.review(code, "python", use_cache=False)
            r_rev, _ = Reviewer().review(code, "python", use_cache=False)
        assert r_app.risk == r_rev.risk
        assert len(r_app.findings) == len(r_rev.findings)
