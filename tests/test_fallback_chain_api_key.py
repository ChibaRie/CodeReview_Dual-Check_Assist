"""fallback_chain.call 显式 api_key 参数 — TDD 单元测试。v0.10

Verifies that FallbackChain.call accepts an optional ``api_key`` argument
and uses it in the Authorization header, taking precedence over any
environment variable.
"""
import json

import pytest
from circuit_breaker import CircuitBreaker
from fallback_chain import FallbackChain, ModelConfig
from static_check import static_check


def test_call_uses_explicit_api_key_when_env_missing(monkeypatch):
    """显式传入 api_key 时，即使环境变量缺失也能调用。"""
    # Ensure the env var the model references is NOT set
    monkeypatch.delenv("TEST_DEEPSEEK_API_KEY", raising=False)

    model = ModelConfig(
        name="deepseek",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        api_key_env="TEST_DEEPSEEK_API_KEY",
        model="deepseek-chat",
        timeout=30,
    )
    cb = CircuitBreaker(threshold=1, cooldown=60)
    chain = FallbackChain([model], cb)

    import urllib.request
    from unittest.mock import MagicMock, patch

    mock_response = {"choices": [{"message": {"content": '{"confirmation": []}'}}]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        sr = static_check("x = 1\n", "python")
        result = chain.call("prompt", sr, api_key="sk-test-key")
        assert result.tier == "deepseek"
        assert mock_urlopen.called
        # 验证请求头携带了显式传入的 key
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.headers["Authorization"] == "Bearer sk-test-key"


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    """显式 api_key 优先于环境变量。"""
    monkeypatch.setenv("TEST_DEEPSEEK_API_KEY", "sk-env-value")

    model = ModelConfig(
        name="deepseek",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        api_key_env="TEST_DEEPSEEK_API_KEY",
        model="deepseek-chat",
        timeout=30,
    )
    cb = CircuitBreaker(threshold=1, cooldown=60)
    chain = FallbackChain([model], cb)

    import urllib.request
    from unittest.mock import MagicMock, patch

    mock_response = {"choices": [{"message": {"content": "{}"}}]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        sr = static_check("y = 2\n", "python")
        result = chain.call("prompt", sr, api_key="sk-explicit")
        assert result.tier == "deepseek"
        req = mock_urlopen.call_args[0][0]
        # 显式 key 必须覆盖环境变量
        assert req.headers["Authorization"] == "Bearer sk-explicit"
        assert req.headers["Authorization"] != "Bearer sk-env-value"


def test_call_without_api_key_falls_back_to_env(monkeypatch):
    """不传 api_key 时，回退到环境变量（保持向后兼容）。"""
    monkeypatch.setenv("TEST_DEEPSEEK_API_KEY", "sk-from-env")

    model = ModelConfig(
        name="deepseek",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        api_key_env="TEST_DEEPSEEK_API_KEY",
        model="deepseek-chat",
        timeout=30,
    )
    cb = CircuitBreaker(threshold=1, cooldown=60)
    chain = FallbackChain([model], cb)

    import urllib.request
    from unittest.mock import MagicMock, patch

    mock_response = {"choices": [{"message": {"content": "{}"}}]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        sr = static_check("z = 3\n", "python")
        # 不传 api_key
        result = chain.call("prompt", sr)
        assert result.tier == "deepseek"
        req = mock_urlopen.call_args[0][0]
        assert req.headers["Authorization"] == "Bearer sk-from-env"


def test_no_api_key_no_env_still_falls_to_local(monkeypatch):
    """无 api_key 且环境变量缺失 → Tier 3 本地兜底。"""
    monkeypatch.delenv("TEST_DEEPSEEK_API_KEY", raising=False)

    model = ModelConfig(
        name="deepseek",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        api_key_env="TEST_DEEPSEEK_API_KEY",
        model="deepseek-chat",
        timeout=30,
    )
    cb = CircuitBreaker(threshold=1, cooldown=60)
    chain = FallbackChain([model], cb)

    sr = static_check("a = 4\n", "python")
    result = chain.call("prompt", sr)
    assert result.tier == "local_fallback"
    assert result.attempts[0]["success"] is False