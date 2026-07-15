"""FastAPI web_server 端点测试 — TDD。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from web_server import app
    return TestClient(app)


def test_review_endpoint_exists(client):
    response = client.post("/api/review", json={
        "code": "x = 1\n",
        "lang": "python",
        "api_key": "",
        "use_cache": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert "risk" in data
    assert "findings" in data


def test_batch_endpoint(client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.go").write_text("package main\n", encoding="utf-8")
    response = client.post("/api/batch", json={
        "directory": str(tmp_path),
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 200
    data = response.json()
    assert "batch_summary" in data
    assert "files" in data
    assert data["batch_summary"]["total_files"] == 2


def test_batch_invalid_directory_returns_400(client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    response = client.post("/api/batch", json={
        "directory": "this_dir_does_not_exist_12345",
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data


def test_batch_rejects_path_traversal_returns_400(client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    response = client.post("/api/batch", json={
        "directory": "../..",
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data


def test_batch_rejects_absolute_path_outside_root_returns_400(client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    outside = tmp_path.parent
    response = client.post("/api/batch", json={
        "directory": str(outside),
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "health" in data


def test_breaker_endpoint(client):
    response = client.get("/api/breaker")
    assert response.status_code == 200


def test_breaker_reset_endpoint(client):
    response = client.post("/api/breaker/reset", json={"lang": "python"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["lang"] == "python"


def test_breaker_reset_all(client):
    response = client.post("/api/breaker/reset", json={"lang": ""})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["lang"] == "all"


def test_vector_stats_endpoint(client):
    response = client.get("/api/vector/stats")
    assert response.status_code == 200


def test_trend_endpoint(client):
    response = client.get("/api/trend")
    assert response.status_code == 200


def test_review_rejects_invalid_lang(client):
    response = client.post("/api/review", json={
        "code": "x = 1\n",
        "lang": "cpp",
        "api_key": "",
        "use_cache": True,
    })
    assert response.status_code == 422


def test_batch_rejects_invalid_lang(client):
    response = client.post("/api/batch", json={
        "directory": "data",
        "lang": "cpp",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 422


def test_api_key_not_in_response(client):
    response = client.post("/api/review", json={
        "code": "x = 1\n",
        "lang": "python",
        "api_key": "sk-secret-test-key",
        "use_cache": False,
    })
    assert response.status_code == 200
    text = response.text
    assert "sk-secret-test-key" not in text


@pytest.mark.parametrize("endpoint,method,expected_status", [
    ("/api/health", "get", 503),
    ("/api/breaker", "get", 500),
    ("/api/vector/stats", "get", 500),
    ("/api/trend", "get", 500),
])
def test_error_endpoints_return_structured_json(client, monkeypatch, endpoint, method, expected_status):
    def boom():
        raise RuntimeError("internal boom")
    monkeypatch.setattr("web_server._cache_dir", boom)
    response = getattr(client, method)(endpoint)
    assert response.status_code == expected_status
    data = response.json()
    assert "detail" in data
    assert "internal boom" not in response.text


def test_breaker_reset_returns_structured_json_on_failure(client, monkeypatch):
    def boom():
        raise RuntimeError("breaker boom")
    monkeypatch.setattr("web_server._load_breaker_pool", boom)
    response = client.post("/api/breaker/reset", json={"lang": "python"})
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "breaker boom" not in response.text


# ---------------------------------------------------------------------------
# Task 11: 后端测试补充 — 深度结构验证 & 边界用例
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["python", "java", "go", "javascript"])
def test_review_accepts_all_supported_langs(client, lang):
    """POST /api/review 应接受 LANG_PATTERN 中定义的所有四种语言。"""
    response = client.post("/api/review", json={
        "code": "x = 1\n",
        "lang": lang,
        "api_key": "",
        "use_cache": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert "risk" in data
    assert "findings" in data


@pytest.mark.parametrize("lang", ["python", "java", "go", "javascript"])
def test_batch_accepts_all_supported_langs(client, tmp_path: Path, monkeypatch, lang):
    """POST /api/batch 应接受 LANG_PATTERN 中定义的所有四种语言。"""
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    response = client.post("/api/batch", json={
        "directory": str(tmp_path),
        "lang": lang,
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 200
    data = response.json()
    assert "batch_summary" in data
    assert "files" in data


def test_breaker_status_returns_dict_per_lang(client):
    """GET /api/breaker 应返回按语言键控的熔断器状态字典。"""
    response = client.get("/api/breaker")
    assert response.status_code == 200
    data = response.json()
    # status() 返回 {lang: CircuitBreaker.to_dict()} — 顶层应为 dict
    assert isinstance(data, dict)
    # 至少应包含 python 槽（create_pool 默认初始化）
    assert "python" in data
    python_cb = data["python"]
    # CircuitBreaker.to_dict 至少包含 state 字段
    assert "state" in python_cb


def test_breaker_reset_specific_lang_changes_state(client):
    """POST /api/breaker/reset 对特定语言应重置其熔断器到 CLOSED。"""
    # reset python
    response = client.post("/api/breaker/reset", json={"lang": "python"})
    assert response.status_code == 200
    # 验证状态变更生效
    status = client.get("/api/breaker").json()
    assert status["python"]["state"] == "CLOSED"


def test_breaker_reset_missing_lang_field_returns_422(client):
    """POST /api/breaker/reset 缺少 JSON body 应返回 422（无 body）。"""
    response = client.post("/api/breaker/reset")
    # FastAPI 对空 body 期望 application/json，返回 422
    assert response.status_code == 422


def test_vector_stats_returns_expected_shape(client):
    """GET /api/vector/stats 应返回 total_patterns / top_kinds / by_language 字段。"""
    response = client.get("/api/vector/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_patterns" in data
    assert "top_kinds" in data
    assert "by_language" in data
    assert isinstance(data["top_kinds"], list)
    assert isinstance(data["by_language"], list)


def test_trend_returns_parsed_json_dict(client):
    """GET /api/trend 应返回解析后的 JSON 字典而非原始字符串。"""
    response = client.get("/api/trend")
    assert response.status_code == 200
    data = response.json()
    # trend_analyze 返回 TrendReport，fmt_trend_json 序列化为 JSON 字符串，
    # 端点又用 json.loads 解析回 dict — 响应体应为可索引的 dict
    assert isinstance(data, dict)
    # TrendReport 总会包含 overall_trend / overall_avg_score / suggestion 字段
    assert "overall_trend" in data
    assert "overall_avg_score" in data
    assert "suggestion" in data


def test_review_invalid_long_code_returns_422(client):
    """POST /api/review 对超过 max_length 的 code 应返回 422。"""
    response = client.post("/api/review", json={
        "code": "x" * 200_001,
        "lang": "python",
        "api_key": "",
        "use_cache": True,
    })
    assert response.status_code == 422


def test_batch_invalid_line_threshold_zero_returns_422(client):
    """POST /api/batch line_threshold < 1 应返回 422。"""
    response = client.post("/api/batch", json={
        "directory": "data",
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 0,
    })
    assert response.status_code == 422


def test_batch_empty_directory_returns_200(client, tmp_path: Path, monkeypatch):
    """POST /api/batch 对合法但无源码文件的目录应返回 200 和空文件列表。"""
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    (tmp_path / "README.md").write_text("empty", encoding="utf-8")
    response = client.post("/api/batch", json={
        "directory": str(tmp_path),
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["batch_summary"]["total_files"] == 0
    assert data["files"] == []


def test_batch_file_pool_classification(client, tmp_path: Path, monkeypatch):
    """POST /api/batch 应按 line_threshold 正确分类 small / large 文件。"""
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    # small file (< 3 lines)
    (tmp_path / "small.py").write_text("x = 1\n", encoding="utf-8")
    # large file (>= 3 lines, line_threshold=2)
    (tmp_path / "large.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    response = client.post("/api/batch", json={
        "directory": str(tmp_path),
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 2,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["batch_summary"]["total_files"] == 2
    assert data["batch_summary"]["small_files"] == 1
    assert data["batch_summary"]["large_files"] == 1
    pools = {f["file"]: f["pool"] for f in data["files"]}
    assert pools["small.py"] == "normal"
    assert pools["large.py"] == "large"


def test_review_internal_error_returns_500_structured(client, monkeypatch):
    """POST /api/review 内部异常应返回 500 和结构化 detail，不泄漏原始异常。"""
    def boom(*args, **kwargs):
        raise RuntimeError("review boom")
    monkeypatch.setattr("skill.scripts.reviewer.Reviewer.review", boom)
    response = client.post("/api/review", json={
        "code": "x = 1\n",
        "lang": "python",
        "api_key": "",
        "use_cache": False,
    })
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "review boom" not in response.text


def test_batch_internal_file_error_is_captured(client, tmp_path: Path, monkeypatch):
    """POST /api/batch 单个文件评审失败应被捕获，结果含 ERROR 标记。"""
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    (tmp_path / "bad.py").write_text("x = 1\n", encoding="utf-8")
    def boom(self, **kwargs):
        raise RuntimeError("file boom")
    monkeypatch.setattr("skill.scripts.reviewer.Reviewer.review", boom)
    response = client.post("/api/batch", json={
        "directory": str(tmp_path),
        "lang": "python",
        "api_key": "",
        "use_cache": False,
        "line_threshold": 500,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["batch_summary"]["total_files"] == 1
    assert data["files"][0]["risk"].startswith("ERROR")


def test_api_key_not_in_batch_response(client, tmp_path: Path, monkeypatch):
    """POST /api/batch 响应体不应包含传入的 api_key 明文。"""
    monkeypatch.setattr("web_server.PROJECT_ROOT", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    secret = "sk-batch-secret-test-key"
    response = client.post("/api/batch", json={
        "directory": str(tmp_path),
        "lang": "python",
        "api_key": secret,
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 200
    assert secret not in response.text


def test_breaker_reset_invalid_lang_pattern_returns_422(client):
    """POST /api/breaker/reset 对不在 pattern 中的 lang 应返回 422。"""
    response = client.post("/api/breaker/reset", json={"lang": "ruby"})
    assert response.status_code == 422


def test_cors_headers_present(client):
    """FastAPI 应在 OPTIONS 预检请求上返回 CORS 头。"""
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in {k.lower() for k in response.headers}


def test_health_endpoint_returns_expected_fields(client):
    """GET /api/health 返回的 dict 应包含 health 字段。"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "health" in data
    # health_check_run 返回的 dict 至少包含 status / cache_dir 等字段
    # 不强约束模式，仅验证顶层为 dict 且有 health 键
    assert isinstance(data, dict)
