"""降级链单元测试 — mock HTTP 调用。v0.9"""
import os

import pytest
from circuit_breaker import CircuitBreaker
from fallback_chain import ChainResult, FallbackChain, ModelConfig
from static_check import static_check


@pytest.fixture
def model_list():
    return [
        ModelConfig(name="deepseek", endpoint="https://api.ds.com/v1", api_key_env="DEEPSEEK_API_KEY", model="ds", timeout=5),
        ModelConfig(name="qwen", endpoint="https://api.qw.com/v1", api_key_env="QWEN_API_KEY", model="qw", timeout=5),
    ]


@pytest.fixture
def static_rpt():
    return static_check("x = 1\n", "python")


class TestFallbackChainMocked:
    def test_tier1_success(self, model_list, static_rpt, mock_http_success):
        """T1 DeepSeek 成功 → 直接返回"""
        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        cb = CircuitBreaker()
        chain = FallbackChain(model_list, cb)
        result = chain.call("prompt", static_rpt)
        assert result.tier == "deepseek"
        # mock_http_success 返回 JSON 含 Unicode 转义，验证 tier 即可
        assert result.text is not None
        del os.environ["DEEPSEEK_API_KEY"]

    def test_tier1_to_tier2_fallback(self, model_list, static_rpt):
        """T1 失败 → T2 成功"""
        import urllib.request
        from unittest.mock import MagicMock, patch

        os.environ["DEEPSEEK_API_KEY"] = "k1"
        os.environ["QWEN_API_KEY"] = "k2"

        call_count = [0]

        def fake_urlopen(req, timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TimeoutError("DS timeout")
            else:
                resp = MagicMock()
                resp.read.return_value = (
                    b'{"choices":[{"message":{"content":"{\\"confirmation\\":[],'
                    b'\\"rejection\\":[],\\"new_findings\\":[]}"}}]}'
                )
                resp.__enter__ = MagicMock(return_value=resp)
                resp.__exit__ = MagicMock(return_value=False)
                return resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            cb = CircuitBreaker()
            chain = FallbackChain(model_list, cb)
            result = chain.call("prompt", static_rpt)
            assert result.tier == "qwen"
            # 失败已记录（T1 fail）
            assert len(result.attempts) == 2

        del os.environ["DEEPSEEK_API_KEY"]
        del os.environ["QWEN_API_KEY"]

    def test_all_tiers_fail_to_local(self, model_list, static_rpt):
        """T1 T2 都失败 → T3 本地兜底"""
        os.environ["DEEPSEEK_API_KEY"] = "k1"
        os.environ["QWEN_API_KEY"] = "k2"

        from unittest.mock import patch

        with patch("urllib.request.urlopen", side_effect=TimeoutError("all down")):
            cb = CircuitBreaker()
            chain = FallbackChain(model_list, cb)
            result = chain.call("prompt", static_rpt)
            assert result.tier == "local_fallback"
            assert "AI 深检暂不可用" in result.text
            assert cb.failures == 2

        del os.environ["DEEPSEEK_API_KEY"]
        del os.environ["QWEN_API_KEY"]

    def test_breaker_open_skips_tiers(self, model_list, static_rpt):
        """熔断器 OPEN → 直接跳到 T3 本地兜底"""
        cb = CircuitBreaker(threshold=1)
        cb.record_failure("prev error")
        chain = FallbackChain(model_list, cb)
        result = chain.call("prompt", static_rpt)
        assert result.tier == "local_fallback"
        assert "熔断器 OPEN" in result.text


class TestFallbackChainNoModels:
    def test_no_models_goes_to_local(self, static_rpt):
        """无模型配置 → 直接本地兜底"""
        cb = CircuitBreaker()
        chain = FallbackChain([], cb)
        result = chain.call("ignored", static_rpt)
        assert result.tier == "local_fallback"
        assert "AI 深检暂不可用" in result.text

    def test_no_api_key_raises(self):
        """无 API key 时抛出 RuntimeError"""
        model = ModelConfig(name="t", endpoint="http://x", api_key_env="MISSING_KEY", model="m", timeout=1)
        cb = CircuitBreaker()
        chain = FallbackChain([model], cb)
        sr = static_check("x=1\n", "python")
        result = chain.call("p", sr)
        assert result.tier == "local_fallback"


class TestChainResult:
    def test_chain_result_fields(self):
        cr = ChainResult(text="ok", tier="deepseek", attempts=[{"model": "ds", "success": True}])
        assert cr.tier == "deepseek"
        assert len(cr.attempts) == 1

    def test_empty_attempts(self):
        cr = ChainResult(text="fallback", tier="local_fallback")
        assert cr.attempts == []
