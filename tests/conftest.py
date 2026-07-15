"""pytest 共享 fixtures 和 mock 工具。v0.9"""
import json
import os
import sys
import tempfile
import threading
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录与 skill/scripts 在 sys.path 中
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_SCRIPTS = str(Path(__file__).resolve().parents[1] / "skill" / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


# ── 代码样本 fixtures ────────────────────────────────────


@pytest.fixture
def python_buggy_code():
    return """def add_item(item, cache=[]):
    cache.append(item)
    return cache

def read_file(path):
    try:
        f = open(path)
        return f.read()
    except:
        return ""

def classify(value):
    if value is True:
        if value is not None:
            if value != False:
                if value == 1:
                    return "yes"
    return "no"

# TODO: refactor this before release
"""


@pytest.fixture
def python_clean_code():
    return """def add_item(item, cache=None):
    if cache is None:
        cache = []
    cache.append(item)
    return cache

def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""
"""


@pytest.fixture
def java_code():
    return """import org.hibernate.Session;
import org.hibernate.query.Query;
import java.util.List;

public class UserDao {
    // BUG: SQL 注入 — 字符串拼接在 createQuery 内
    public User findBydept(String deptName) {
        Session session = HibernateUtil.getSessionFactory().openSession();
        Query<User> query = session.createQuery("FROM User WHERE dept = '" + deptName + "'");
        List<User> results = query.list();
        session.close();
        return results.isEmpty() ? null : results.get(0);
    }
}

class HibernateUtil {
    static SessionFactory getSessionFactory() { return null; }
}
class SessionFactory { Session openSession() { return null; } }
class User {}
"""


@pytest.fixture
def go_issues_code():
    return """package main

import (
    "fmt"
    "os"
)

// BUG: 包级可变变量
var globalCounter int = 0

// BUG: 未检查错误返回值
func readFile(path string) string {
    data, err := os.ReadFile(path)
    return string(data)
}

// BUG: defer 在循环中
func processFiles(paths []string) {
    for _, p := range paths {
        f, _ := os.Open(p)
        defer f.Close()
        fmt.Println(f.Name())
    }
}
"""


@pytest.fixture
def js_issues_code():
    return """// BUG: var 声明
var userName = "admin";

// BUG: == 代替 ===
function isAdmin(role) {
    if (role == "admin") {
        return true;
    }
    return false;
}

// BUG: console.log 调试残留
function fetchData(id) {
    console.log("fetching:", id);
    return fetch("/api/" + id);
}
"""


@pytest.fixture
def go_code():
    return """package main

import "fmt"

// TODO: add proper error handling
func processData(input []int) []int {
    result := make([]int, 0)
    for _, v := range input {
        if v > 0 {
            result = append(result, v*2)
        }
    }
    return result
}

// FIXME: this function is too long and needs refactoring — this is a very long comment line to trigger the long line detector in the static checker
func main() {
    fmt.Println("breaker isolation test")
}
"""


# ── 临时目录 fixtures ─────────────────────────────────────


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def temp_cache_dir(temp_dir):
    d = temp_dir / ".cache"
    d.mkdir()
    return d


# ── 边界样本 fixtures ────────────────────────────────────


@pytest.fixture
def empty_code():
    return ""


@pytest.fixture
def unicode_code():
    return '''def greet(name: str) -> str:
    """打招呼 — 含中文注释、emoji、日文"""
    # 🎉 欢迎信息
    greeting = f"こんにちは、{name}！ 🚀"
    return greeting
'''


@pytest.fixture
def very_large_code():
    """生成 ~2000 行代码用于大文件测试。"""
    lines = ["def large_function_000():"]
    for i in range(2000):
        lines.append(f"    x{i} = {i} + {i}")
    lines.append("    return x0")
    return "\n".join(lines)


@pytest.fixture
def special_chars_code():
    return '''def parse_regex_patterns():
    patterns = {
        "email": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\\\.[a-zA-Z]{2,}$",
        "url": r"https?://(?:www\\\\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\\\\.[a-zA-Z0-9()]{1,6}",
        "path": "C:\\\\Users\\\\test\\\\Documents",
    }
    return patterns
'''


# ── Mock 工具 ─────────────────────────────────────────────


@pytest.fixture
def mock_http_success():
    """Mock urllib.request.urlopen 返回成功的 AI 响应。"""
    response_body = json.dumps({
        "choices": [{
            "message": {
                "content": json.dumps({
                    "confirmation": [],
                    "rejection": [],
                    "new_findings": [
                        {"line": 2, "kind": "logic_error", "severity": "high",
                         "message": "缺少除零保护"}
                    ],
                })
            }
        }]
    }).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        yield mock_resp


@pytest.fixture
def mock_http_failure():
    """Mock urllib.request.urlopen 抛出超时异常。"""
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        yield


@pytest.fixture
def mock_http_auth_error():
    """Mock urllib.request.urlopen 抛出认证错误。"""
    with patch("urllib.request.Request") as mock_req:
        mock_req.side_effect = Exception("401 Unauthorized")
        yield


# ── 并发测试工具 ──────────────────────────────────────────


def run_concurrent(func, args_list: list, max_workers: int = 5):
    """在多个线程中并发运行 func，返回结果列表。"""
    results = []
    errors = []
    lock = threading.Lock()

    def _worker(args):
        try:
            r = func(*args) if isinstance(args, tuple) else func(args)
            with lock:
                results.append(r)
        except Exception as e:
            with lock:
                errors.append(e)

    threads = []
    for a in args_list:
        t = threading.Thread(target=_worker, args=(a,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=10)

    return results, errors
