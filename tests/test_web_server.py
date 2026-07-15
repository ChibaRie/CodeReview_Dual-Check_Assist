"""FastAPI web_server 端点测试 — TDD。"""
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


def test_batch_endpoint(client, tmp_path: Path):
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


def test_batch_invalid_directory(client):
    response = client.post("/api/batch", json={
        "directory": "this_dir_does_not_exist_12345",
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 200
    data = response.json()
    assert "error" in data


def test_batch_rejects_path_traversal(client):
    response = client.post("/api/batch", json={
        "directory": "../..",
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 200
    data = response.json()
    assert "error" in data


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
