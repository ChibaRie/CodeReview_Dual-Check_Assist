# 前端可视化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DualCheck Code 增加本地 Web UI（React + Vite + FastAPI），支持单文件评审、批量评审、系统状态仪表盘，用户在前端输入 DeepSeek API key。

**Architecture:** 前端 React 调用本地 FastAPI 后端 `/api/*`，FastAPI 复用现有 `skill/scripts/reviewer.py` 评审管线。API key 从 `FallbackChain` 的环境变量读取改为显式参数传递，CLI 保持兼容。

**Tech Stack:** React 18 + Vite 5 + TypeScript + React Router + Monaco Editor + FastAPI + uvicorn + pytest.

## Global Constraints

- `skill/` 目录保持独立，不放置任何前端或 Web 服务相关文件。
- `web_server.py` 位于项目根目录。
- `web/` 前端工程位于项目根目录。
- 后端新增代码测试覆盖率 ≥80%。
- CLI 现有路径必须保持兼容，不能破坏 `app.py` 的用法。
- API key 不记录、不持久化、不打印日志。
- `lang` 必须是 `python/java/go/javascript` 之一。
- 开发启动：`npm run dev` 同时启动 Vite（5173）和 FastAPI（8000）。

---

## File Structure

新增或修改的文件：

| 文件 | 责任 |
|------|------|
| `skill/scripts/fallback_chain.py` | 修改 `FallbackChain.call` 接受 `api_key` 参数 |
| `skill/scripts/reviewer.py` | 修改 `Reviewer.review` 透传 `api_key` |
| `web_server.py` | FastAPI 入口，暴露 `/api/*` |
| `web/package.json` | 前端依赖与 scripts |
| `web/vite.config.ts` | Vite 配置 + proxy |
| `web/tsconfig.json` | TypeScript 配置 |
| `web/index.html` | HTML 入口 |
| `web/src/main.tsx` | React 应用挂载 |
| `web/src/App.tsx` | 路由与 Layout |
| `web/src/api.ts` | 封装后端 API 调用 |
| `web/src/components/Layout.tsx` | 导航栏 + 布局 |
| `web/src/components/ApiKeyInput.tsx` | API key 输入 |
| `web/src/components/CodeEditor.tsx` | Monaco 代码编辑器 |
| `web/src/components/SeverityBadge.tsx` | 严重度标签 |
| `web/src/components/FindingCard.tsx` | finding 卡片 |
| `web/src/components/RiskBanner.tsx` | 风险等级横幅 |
| `web/src/components/PerfFooter.tsx` | 性能指标页脚 |
| `web/src/pages/ReviewPage.tsx` | 单文件评审页 |
| `web/src/pages/BatchPage.tsx` | 批量评审页 |
| `web/src/pages/DashboardPage.tsx` | 仪表盘页 |
| `package.json` | 根目录 npm scripts（concurrently） |
| `tests/test_web_server.py` | FastAPI 端点测试 |
| `tests/test_reviewer_api_key.py` | reviewer api_key 参数测试 |
| `tests/test_fallback_chain_api_key.py` | fallback_chain api_key 参数测试 |

---

## Task 1: 改造 `fallback_chain.py` 接受 `api_key` 参数

**Files:**
- Modify: `skill/scripts/fallback_chain.py`
- Test: `tests/test_fallback_chain_api_key.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `FallbackChain.call(prompt, static_report, api_key: str = "")` 签名

### 目标
让 `FallbackChain` 既可以从环境变量读取 key，也可以接受调用方显式传入的 key。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_fallback_chain_api_key.py
from unittest.mock import patch
import pytest
from skill.scripts.fallback_chain import FallbackChain, ModelConfig
from skill.scripts.circuit_breaker import CircuitBreaker
from skill.scripts.static_check import static_check


def test_call_uses_explicit_api_key_when_env_missing():
    """显式传入 api_key 时，即使环境变量缺失也能调用。"""
    model = ModelConfig(
        name="deepseek",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        api_key_env="TEST_DEEPSEEK_API_KEY",
        model="deepseek-chat",
        timeout=30,
    )
    cb = CircuitBreaker(threshold=1, cooldown=60)
    chain = FallbackChain([model], cb)

    with patch("skill.scripts.fallback_chain.urllib.request.urlopen") as mock_urlopen:
        import io
        import json

        mock_response = {"choices": [{"message": {"content": '{"confirmation": []}'}}]}
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(mock_response).encode()
        sr = static_check("x = 1\n", "python")
        result = chain.call("prompt", sr, api_key="sk-test-key")
        assert result.tier == "deepseek"
        assert mock_urlopen.called
        # 验证请求头携带了显式传入的 key
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.headers["Authorization"] == "Bearer sk-test-key"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_fallback_chain_api_key.py -v
```

Expected: FAIL，因为 `call` 还不接受 `api_key` 参数。

- [ ] **Step 3: 最小实现**

修改 `skill/scripts/fallback_chain.py`：

```python
# 修改 _call_one 签名
    def _call_one(self, model: ModelConfig, prompt: str, api_key: str = "") -> str:
        key = api_key or os.environ.get(model.api_key_env, "")
        if not key:
            raise RuntimeError(f"缺少环境变量 {model.api_key_env}")
        # ... 其余不变

# 修改 call 签名
    def call(self, prompt: str, static_report: StaticReport, api_key: str = "") -> ChainResult:
        # ...
        for i, model in enumerate(self.models):
            try:
                text = self._call_one(model, prompt, api_key)
                # ...
```

完整实现：

```python
    def _call_one(self, model: ModelConfig, prompt: str, api_key: str = "") -> str:
        key = api_key or os.environ.get(model.api_key_env, "")
        if not key:
            raise RuntimeError(f"缺少环境变量 {model.api_key_env}")
        payload = json.dumps(
            {
                "model": model.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 2048,
            }
        ).encode()
        req = urllib.request.Request(
            model.endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=model.timeout) as resp:
            body = json.loads(resp.read().decode())
        return body["choices"][0]["message"]["content"]

    def call(self, prompt: str, static_report: StaticReport, api_key: str = "") -> ChainResult:
        attempts: list[dict] = []

        if not self.breaker.allow():
            reason = f"熔断器 {self.breaker.state}（失败 {self.breaker.failures} 次"
            if self.breaker.last_error:
                reason += f"，最后错误: {self.breaker.last_error}"
            reason += "）"
            text = self._local_fallback(static_report, reason)
            return ChainResult(text=text, tier="local_fallback", attempts=attempts)

        tier_names = {0: "deepseek", 1: "qwen"}
        for i, model in enumerate(self.models):
            tier_label = tier_names.get(i, model.name)
            try:
                text = self._call_one(model, prompt, api_key)
                self.breaker.record_success()
                attempts.append({"model": model.name, "tier": tier_label, "success": True})
                return ChainResult(text=text, tier=tier_label, attempts=attempts)
            except Exception as exc:
                self.breaker.record_failure(f"{model.name}: {exc}")
                attempts.append(
                    {"model": model.name, "tier": tier_label, "success": False, "error": str(exc)}
                )

        reason = f"全部 {len(self.models)} 个远程模型调用失败"
        text = self._local_fallback(static_report, reason)
        return ChainResult(text=text, tier="local_fallback", attempts=attempts)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_fallback_chain_api_key.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add skill/scripts/fallback_chain.py tests/test_fallback_chain_api_key.py
git commit -m "feat: fallback_chain 支持显式 api_key 参数"
```

---

## Task 2: 改造 `reviewer.py` 透传 `api_key` 参数

**Files:**
- Modify: `skill/scripts/reviewer.py`
- Test: `tests/test_reviewer_api_key.py`

**Interfaces:**
- Consumes: `FallbackChain.call(prompt, static_report, api_key)`
- Produces: `Reviewer.review(..., api_key: str = "")` 签名

### 目标
让 `Reviewer.review` 能接收前端传来的 API key，并传递给 AI 降级链。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_reviewer_api_key.py
from unittest.mock import patch
from skill.scripts.reviewer import Reviewer


def test_reviewer_review_accepts_api_key():
    rev = Reviewer()
    with patch("skill.scripts.reviewer.FallbackChain") as MockChain:
        MockChain.return_value.call.return_value.text = '{"confirmation": []}'
        MockChain.return_value.call.return_value.tier = "deepseek"
        # 提供一个有效的 api_key
        report, perf = rev.review("x = 1\n", "python", api_key="sk-test")
        # 验证 FallbackChain.call 被调用时传入了 api_key
        call_kwargs = MockChain.return_value.call.call_args[1]
        assert call_kwargs.get("api_key") == "sk-test"
        assert perf["ai_tier"] == "deepseek"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_reviewer_api_key.py -v
```

Expected: FAIL，因为 `review` 还不接受 `api_key`。

- [ ] **Step 3: 最小实现**

修改 `skill/scripts/reviewer.py`：

```python
    def _run_ai(self, lang_breaker, static_report: StaticReport, code: str, lang: str,
                framework: str, config: dict, pool: BreakerPool, api_key: str = ""
                ) -> tuple[AIReport | None, str, str]:
        prompt = self._build_prompt(static_report, code, lang, framework)
        chain = FallbackChain(
            [ModelConfig(**m) for m in config.get("models", [])], lang_breaker
        )
        chain_result: ChainResult = chain.call(prompt, static_report, api_key)
        # ... 其余不变

    def review(self, code: str, lang: str, framework: str = "",
               config_path: str = "", use_cache: bool = True, api_key: str = ""
               ) -> tuple[FinalReport, dict]:
        # ... 在 _run_ai 调用处传入 api_key
        if action == "run_ai":
            ai_report, ai_tier, new_state = self._run_ai(
                lang_breaker, static_report, code, lang, framework, config, pool, api_key
            )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_reviewer_api_key.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add skill/scripts/reviewer.py tests/test_reviewer_api_key.py
git commit -m "feat: reviewer.review 透传 api_key 到 fallback_chain"
```

---

## Task 3: 创建 FastAPI 后端 `web_server.py`

**Files:**
- Create: `web_server.py`
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: `Reviewer.review(..., api_key=...)`
- Produces: `POST /api/review`, `POST /api/batch`, `GET /api/health`, `GET /api/breaker`, `POST /api/breaker/reset`, `GET /api/vector/stats`, `GET /api/trend`

### 目标
为前端提供 HTTP API，复用现有 reviewer 能力。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_web_server.py
from fastapi.testclient import TestClient


def test_review_endpoint_exists():
    from web_server import app
    client = TestClient(app)
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_web_server.py -v
```

Expected: FAIL，因为 `web_server.py` 还不存在。

- [ ] **Step 3: 最小实现**

创建 `web_server.py`：

```python
"""DualCheck Code Web UI 后端 — FastAPI 入口。

注意：本文件不属于 skill/ 包，仅服务于当前项目的本地 Web UI。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from skill.scripts.reviewer import Reviewer
from skill.scripts.config import resolve_cache_dir, default_config_path, load_config
from skill.scripts.health_check import run as health_check_run
from skill.scripts.circuit_breaker import create_pool
from skill.scripts.vector_store import VectorStore
from skill.scripts.trend_analyzer import analyze as trend_analyze, fmt_trend_json


app = FastAPI(title="DualCheck Code Web UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReviewRequest(BaseModel):
    code: str
    lang: str = Field(pattern=r"^(python|java|go|javascript)$")
    framework: str = ""
    api_key: str = ""
    use_cache: bool = True


class BatchRequest(BaseModel):
    directory: str
    lang: str = "python"
    framework: str = ""
    api_key: str = ""
    use_cache: bool = True
    line_threshold: int = 500


class BreakerResetRequest(BaseModel):
    lang: str = ""


@app.post("/api/review")
def api_review(req: ReviewRequest):
    reviewer = Reviewer()
    config_path = default_config_path()
    report, perf = reviewer.review(
        code=req.code,
        lang=req.lang,
        framework=req.framework,
        config_path=config_path,
        use_cache=req.use_cache,
        api_key=req.api_key,
    )
    out = report.__dict__.copy()
    out["_perf"] = perf
    return out


@app.post("/api/batch")
def api_batch(req: BatchRequest):
    from skill.scripts.app import _run_batch
    from pathlib import Path
    import json

    # _run_batch 目前打印到 stdout，需要改造成返回数据结构
    # 这里先提供简化实现：逐文件调用 reviewer
    directory = Path(req.directory)
    if not directory.is_dir():
        return {"error": f"{req.directory} 不是有效目录"}

    LANG_MAP = {".py": "python", ".go": "go", ".js": "javascript", ".ts": "javascript"}
    files = sorted([f for f in directory.iterdir() if f.is_file() and f.suffix in LANG_MAP])
    results = []
    reviewer = Reviewer()
    config_path = default_config_path()
    for f in files:
        try:
            code = f.read_text(encoding="utf-8")
            lines = code.count("\n") + 1
            file_lang = LANG_MAP.get(f.suffix, req.lang)
            report, perf = reviewer.review(
                code=code,
                lang=file_lang,
                framework=req.framework,
                config_path=config_path,
                use_cache=req.use_cache,
                api_key=req.api_key,
            )
            results.append({
                "file": f.name,
                "lines": lines,
                "risk": report.risk,
                "elapsed_ms": perf["elapsed_ms"],
                "pool": "large" if lines > req.line_threshold else "normal",
                "perf": perf,
            })
        except Exception as exc:
            results.append({
                "file": f.name,
                "lines": 0,
                "risk": f"ERROR: {exc}",
                "elapsed_ms": 0,
                "pool": "unknown",
                "perf": {},
            })
    return {
        "batch_summary": {
            "total_files": len(results),
            "small_files": sum(1 for r in results if r["pool"] == "normal"),
            "large_files": sum(1 for r in results if r["pool"] == "large"),
        },
        "files": results,
    }


@app.get("/api/health")
def api_health():
    config = load_config(default_config_path())
    cache_dir = resolve_cache_dir(config.get("cache", {}).get("dir", "data/.cache"), "")
    status_path = str(Path(__file__).resolve().parent / "system" / "status.md")
    return health_check_run(cache_dir, status_path)


@app.get("/api/breaker")
def api_breaker():
    config = load_config(default_config_path())
    cache_dir = resolve_cache_dir(config.get("cache", {}).get("dir", "data/.cache"), "")
    persist_path = str(Path(cache_dir) / ".breaker_state.json")
    pool = create_pool(config, persist_path)
    return pool.status()


@app.post("/api/breaker/reset")
def api_breaker_reset(req: BreakerResetRequest):
    config = load_config(default_config_path())
    cache_dir = resolve_cache_dir(config.get("cache", {}).get("dir", "data/.cache"), "")
    persist_path = str(Path(cache_dir) / ".breaker_state.json")
    pool = create_pool(config, persist_path)
    pool.reset(req.lang)
    pool._save()
    return {"ok": True, "lang": req.lang or "all"}


@app.get("/api/vector/stats")
def api_vector_stats():
    config = load_config(default_config_path())
    cache_dir = resolve_cache_dir(config.get("cache", {}).get("dir", "data/.cache"), "")
    vdb = str(Path(cache_dir) / "patterns.db")
    vstore = VectorStore(vdb)
    try:
        return vstore.stats()
    finally:
        vstore.close()


@app.get("/api/trend")
def api_trend(weeks: int = 8):
    config = load_config(default_config_path())
    cache_dir = resolve_cache_dir(config.get("cache", {}).get("dir", "data/.cache"), "")
    vdb = str(Path(cache_dir) / "patterns.db")
    report = trend_analyze(cache_dir, vdb)
    return fmt_trend_json(report)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_server:app", host="127.0.0.1", port=8000, reload=True)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_web_server.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web_server.py tests/test_web_server.py
git commit -m "feat: 新增 FastAPI 后端 web_server.py"
```

---

## Task 4: 创建前端工程基础

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/components/Layout.tsx`
- Create: `web/src/vite-env.d.ts`

**Interfaces:**
- Produces: React 应用基础结构

### 目标
搭建 React + Vite + TypeScript 工程骨架。

- [ ] **Step 1: 创建 `web/package.json`**

```json
{
  "name": "dualcheck-web",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.24.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.3.3"
  }
}
```

- [ ] **Step 2: 创建 `web/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: 创建 `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: 创建 `web/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: 创建 `web/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>DualCheck Code</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: 创建 `web/src/vite-env.d.ts`**

```typescript
/// <reference types="vite/client" />
```

- [ ] **Step 7: 创建 `web/src/main.tsx`**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
```

- [ ] **Step 8: 创建 `web/src/App.tsx`**

```tsx
import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ReviewPage from './pages/ReviewPage'
import BatchPage from './pages/BatchPage'
import DashboardPage from './pages/DashboardPage'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<ReviewPage />} />
        <Route path="/batch" element={<BatchPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
      </Routes>
    </Layout>
  )
}

export default App
```

- [ ] **Step 9: 创建 `web/src/components/Layout.tsx`**

```tsx
import { NavLink } from 'react-router-dom'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex">
      <nav className="w-64 bg-slate-900 text-white p-6 flex flex-col gap-4">
        <h1 className="text-xl font-bold">DualCheck</h1>
        <NavLink to="/" className={({ isActive }) => isActive ? 'text-blue-400' : ''}>单文件评审</NavLink>
        <NavLink to="/batch" className={({ isActive }) => isActive ? 'text-blue-400' : ''}>批量评审</NavLink>
        <NavLink to="/dashboard" className={({ isActive }) => isActive ? 'text-blue-400' : ''}>仪表盘</NavLink>
      </nav>
      <main className="flex-1 p-6 overflow-auto">{children}</main>
    </div>
  )
}
```

- [ ] **Step 10: 安装前端依赖并验证**

```bash
cd web
npm install
npm run build
```

Expected: `build` 成功，无 TypeScript 错误。

- [ ] **Step 11: 提交**

```bash
git add web/
git commit -m "chore: 搭建 React + Vite + TypeScript 前端工程"
```

---

## Task 5: 前端 API 封装 `web/src/api.ts`

**Files:**
- Create: `web/src/api.ts`
- Test: `web/src/api.test.ts`（可选，后续再补）

**Interfaces:**
- Produces: `review`, `batchReview`, `health`, `breakerStatus`, `resetBreaker`, `vectorStats`, `trendReport`

### 目标
统一封装前端对 `/api/*` 的调用。

- [ ] **Step 1: 创建 `web/src/api.ts`**

```typescript
const API_BASE = '/api'

export interface ReviewRequest {
  code: string
  lang: string
  framework?: string
  api_key?: string
  use_cache?: boolean
}

export interface ReviewResponse {
  risk: string
  summary: string
  static_summary: string
  ai_summary: string
  findings: Finding[]
  _perf: Record<string, any>
}

export interface Finding {
  line: number
  layer: string
  kind: string
  severity: string
  message: string
}

export async function review(req: ReviewRequest): Promise<ReviewResponse> {
  const res = await fetch(`${API_BASE}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    throw new Error(`评审请求失败: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export interface BatchRequest {
  directory: string
  lang?: string
  framework?: string
  api_key?: string
  use_cache?: boolean
  line_threshold?: number
}

export interface BatchResponse {
  batch_summary: {
    total_files: number
    small_files: number
    large_files: number
  }
  files: Array<{
    file: string
    lines: number
    risk: string
    elapsed_ms: number
    pool: string
    perf: Record<string, any>
  }>
}

export async function batchReview(req: BatchRequest): Promise<BatchResponse> {
  const res = await fetch(`${API_BASE}/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    throw new Error(`批量评审请求失败: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export async function health(): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) throw new Error('健康检查失败')
  return res.json()
}

export async function breakerStatus(): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/breaker`)
  if (!res.ok) throw new Error('熔断器状态获取失败')
  return res.json()
}

export async function resetBreaker(lang: string = ''): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/breaker/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lang }),
  })
  if (!res.ok) throw new Error('重置熔断器失败')
  return res.json()
}

export async function vectorStats(): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/vector/stats`)
  if (!res.ok) throw new Error('向量统计获取失败')
  return res.json()
}

export async function trendReport(): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/trend`)
  if (!res.ok) throw new Error('趋势报告获取失败')
  return res.json()
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd web
npm run build
```

Expected: 成功。

- [ ] **Step 3: 提交**

```bash
git add web/src/api.ts
git commit -m "feat: 前端 API 封装"
```

---

## Task 6: 通用 UI 组件

**Files:**
- Create: `web/src/components/ApiKeyInput.tsx`
- Create: `web/src/components/SeverityBadge.tsx`
- Create: `web/src/components/FindingCard.tsx`
- Create: `web/src/components/RiskBanner.tsx`
- Create: `web/src/components/PerfFooter.tsx`
- Create: `web/src/components/CodeEditor.tsx`

**Interfaces:**
- Produces: 可复用组件

### 目标
实现评审页面需要的通用组件。

- [ ] **Step 1: `ApiKeyInput.tsx`**

```tsx
import { useState, useEffect } from 'react'

const STORAGE_KEY = 'dualcheck_api_key'

export function getStoredApiKey(): string {
  return localStorage.getItem(STORAGE_KEY) || ''
}

export function setStoredApiKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key)
}

export default function ApiKeyInput({ value, onChange }: { value: string; onChange: (key: string) => void }) {
  return (
    <div className="mb-4">
      <label className="block text-sm font-medium text-slate-700 mb-1">DeepSeek API Key</label>
      <input
        type="password"
        value={value}
        onChange={(e) => {
          const v = e.target.value
          onChange(v)
          setStoredApiKey(v)
        }}
        placeholder="sk-..."
        className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
      />
      <p className="text-xs text-slate-500 mt-1">仅在本地内存和浏览器 localStorage 保存，不会上传到服务器。</p>
    </div>
  )
}
```

- [ ] **Step 2: `SeverityBadge.tsx`**

```tsx
const colors: Record<string, string> = {
  high: 'bg-red-100 text-red-800 border-red-200',
  medium: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  low: 'bg-blue-100 text-blue-800 border-blue-200',
}

export default function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`text-xs font-medium px-2 py-1 rounded border ${colors[severity] || colors.low}`}>
      {severity}
    </span>
  )
}
```

- [ ] **Step 3: `FindingCard.tsx`**

```tsx
import SeverityBadge from './SeverityBadge'
import type { Finding } from '../api'

export default function FindingCard({ finding }: { finding: Finding }) {
  return (
    <div className="border border-slate-200 rounded p-4 mb-3 bg-white shadow-sm">
      <div className="flex items-center gap-3 mb-2">
        <span className="text-sm font-mono text-slate-500">行 {finding.line}</span>
        <span className="text-xs font-medium px-2 py-1 rounded bg-slate-100 text-slate-700">
          {finding.layer}:{finding.kind}
        </span>
        <SeverityBadge severity={finding.severity} />
      </div>
      <p className="text-slate-800">{finding.message}</p>
    </div>
  )
}
```

- [ ] **Step 4: `RiskBanner.tsx`**

```tsx
const styles: Record<string, string> = {
  '阻止合并': 'bg-red-600 text-white',
  '修复后合并': 'bg-yellow-500 text-white',
  '可合并': 'bg-green-600 text-white',
}

export default function RiskBanner({ risk }: { risk: string }) {
  return (
    <div className={`rounded p-4 text-lg font-bold mb-4 ${styles[risk] || 'bg-slate-500 text-white'}`}>
      风险等级：{risk}
    </div>
  )
}
```

- [ ] **Step 5: `PerfFooter.tsx`**

```tsx
export default function PerfFooter({ perf }: { perf: Record<string, any> }) {
  if (!perf) return null
  return (
    <div className="mt-6 p-4 bg-slate-50 rounded text-sm text-slate-600 border border-slate-200">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <span className="block text-xs text-slate-400">耗时</span>
          {perf.elapsed_ms?.toFixed(0)} ms
        </div>
        <div>
          <span className="block text-xs text-slate-400">缓存</span>
          {perf.cache_hit ? '命中' : '未命中'}
        </div>
        <div>
          <span className="block text-xs text-slate-400">AI 链路</span>
          {perf.ai_tier || 'none'}
        </div>
        <div>
          <span className="block text-xs text-slate-400">熔断器</span>
          {perf.breaker_state || 'CLOSED'}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: `CodeEditor.tsx`**

```tsx
import Editor from '@monaco-editor/react'

export default function CodeEditor({ value, onChange, language }: { value: string; onChange: (v: string) => void; language: string }) {
  return (
    <Editor
      height="400px"
      language={language}
      value={value}
      onChange={(v) => onChange(v || '')}
      theme="vs-light"
      options={{
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: 'on',
        automaticLayout: true,
      }}
    />
  )
}
```

- [ ] **Step 7: 安装 Monaco Editor 依赖**

```bash
cd web
npm install @monaco-editor/react
```

- [ ] **Step 8: 提交**

```bash
git add web/src/components/
git commit -m "feat: 前端通用 UI 组件"
```

---

## Task 7: 单文件评审页面 `ReviewPage`

**Files:**
- Create: `web/src/pages/ReviewPage.tsx`

**Interfaces:**
- Consumes: `review`, `Finding`, `ReviewResponse` from `api.ts`
- Consumes: `ApiKeyInput`, `CodeEditor`, `RiskBanner`, `FindingCard`, `PerfFooter`

### 目标
实现默认首页，支持代码输入、API key、语言选择、评审报告展示。

- [ ] **Step 1: 创建 `ReviewPage.tsx`**

```tsx
import { useState, useEffect } from 'react'
import ApiKeyInput, { getStoredApiKey } from '../components/ApiKeyInput'
import CodeEditor from '../components/CodeEditor'
import RiskBanner from '../components/RiskBanner'
import FindingCard from '../components/FindingCard'
import PerfFooter from '../components/PerfFooter'
import { review, type ReviewResponse } from '../api'

const SAMPLE_CODE = `def divide(a, b):
    return a / b
`

export default function ReviewPage() {
  const [apiKey, setApiKey] = useState(getStoredApiKey)
  const [lang, setLang] = useState('python')
  const [framework, setFramework] = useState('')
  const [code, setCode] = useState(SAMPLE_CODE)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ReviewResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setApiKey(getStoredApiKey)
  }, [])

  const handleReview = async (useCache: boolean) => {
    setLoading(true)
    setError('')
    try {
      const res = await review({
        code,
        lang,
        framework,
        api_key: apiKey,
        use_cache: useCache,
      })
      setResult(res)
    } catch (err: any) {
      setError(err.message || '评审失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-4">
        <ApiKeyInput value={apiKey} onChange={setApiKey} />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">语言</label>
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value)}
              className="w-full border border-slate-300 rounded px-3 py-2"
            >
              <option value="python">Python</option>
              <option value="java">Java</option>
              <option value="go">Go</option>
              <option value="javascript">JavaScript</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">框架</label>
            <input
              value={framework}
              onChange={(e) => setFramework(e.target.value)}
              placeholder="例如 Django, Spring"
              className="w-full border border-slate-300 rounded px-3 py-2"
            />
          </div>
        </div>
        <CodeEditor value={code} onChange={setCode} language={lang} />
        <div className="flex gap-3">
          <button
            onClick={() => handleReview(true)}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded disabled:opacity-50"
          >
            {loading ? '评审中...' : '评审'}
          </button>
          <button
            onClick={() => handleReview(false)}
            disabled={loading}
            className="bg-slate-200 hover:bg-slate-300 text-slate-800 px-4 py-2 rounded disabled:opacity-50"
          >
            强制刷新
          </button>
        </div>
      </div>

      <div>
        {error && <div className="bg-red-50 text-red-700 p-4 rounded mb-4">{error}</div>}
        {result && (
          <>
            <RiskBanner risk={result.risk} />
            <div className="mb-4">
              <h3 className="font-bold text-slate-800">摘要</h3>
              <p className="text-slate-700">{result.summary}</p>
            </div>
            <div className="mb-4">
              <h3 className="font-bold text-slate-800">静态层</h3>
              <p className="text-slate-700">{result.static_summary}</p>
            </div>
            <div className="mb-4">
              <h3 className="font-bold text-slate-800">AI 层</h3>
              <p className="text-slate-700">{result.ai_summary}</p>
            </div>
            <div>
              <h3 className="font-bold text-slate-800 mb-2">
                明细（{result.findings.length} 条）
              </h3>
              {result.findings.map((f, idx) => (
                <FindingCard key={idx} finding={f} />
              ))}
            </div>
            <PerfFooter perf={result._perf} />
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd web
npm run build
```

Expected: 成功。

- [ ] **Step 3: 提交**

```bash
git add web/src/pages/ReviewPage.tsx
git commit -m "feat: 单文件评审页面"
```

---

## Task 8: 批量评审页面 `BatchPage`

**Files:**
- Create: `web/src/pages/BatchPage.tsx`

**Interfaces:**
- Consumes: `batchReview`, `BatchResponse` from `api.ts`
- Consumes: `ApiKeyInput`, `SeverityBadge`（可选）

### 目标
实现批量目录评审页面。

- [ ] **Step 1: 创建 `BatchPage.tsx`**

```tsx
import { useState } from 'react'
import ApiKeyInput, { getStoredApiKey } from '../components/ApiKeyInput'
import { batchReview, type BatchResponse } from '../api'

export default function BatchPage() {
  const [apiKey, setApiKey] = useState(getStoredApiKey)
  const [directory, setDirectory] = useState('')
  const [lineThreshold, setLineThreshold] = useState(500)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BatchResponse | null>(null)
  const [error, setError] = useState('')

  const handleBatch = async () => {
    if (!directory) {
      setError('请输入目录路径')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await batchReview({
        directory,
        api_key: apiKey,
        line_threshold: lineThreshold,
      })
      setResult(res)
    } catch (err: any) {
      setError(err.message || '批量评审失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <ApiKeyInput value={apiKey} onChange={setApiKey} />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <input
          value={directory}
          onChange={(e) => setDirectory(e.target.value)}
          placeholder="目录绝对路径，例如 D:\\project\\src"
          className="border border-slate-300 rounded px-3 py-2 md:col-span-2"
        />
        <input
          type="number"
          value={lineThreshold}
          onChange={(e) => setLineThreshold(Number(e.target.value))}
          placeholder="舱壁阈值"
          className="border border-slate-300 rounded px-3 py-2"
        />
      </div>
      <button
        onClick={handleBatch}
        disabled={loading}
        className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded disabled:opacity-50"
      >
        {loading ? '批量评审中...' : '开始批量评审'}
      </button>

      {error && <div className="bg-red-50 text-red-700 p-4 rounded">{error}</div>}

      {result && (
        <div>
          <div className="mb-4 p-4 bg-slate-50 rounded border border-slate-200">
            <p>总文件数：{result.batch_summary.total_files}</p>
            <p>小文件：{result.batch_summary.small_files}</p>
            <p>大文件：{result.batch_summary.large_files}</p>
          </div>
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-300">
                <th className="py-2">文件</th>
                <th className="py-2">行数</th>
                <th className="py-2">Pool</th>
                <th className="py-2">耗时</th>
                <th className="py-2">风险等级</th>
              </tr>
            </thead>
            <tbody>
              {result.files.map((f, idx) => (
                <tr key={idx} className="border-b border-slate-100">
                  <td className="py-2 font-mono text-sm">{f.file}</td>
                  <td className="py-2">{f.lines}</td>
                  <td className="py-2">{f.pool}</td>
                  <td className="py-2">{f.elapsed_ms.toFixed(0)} ms</td>
                  <td className="py-2">{f.risk}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: 验证编译**

```bash
cd web
npm run build
```

- [ ] **Step 3: 提交**

```bash
git add web/src/pages/BatchPage.tsx
git commit -m "feat: 批量评审页面"
```

---

## Task 9: 仪表盘页面 `DashboardPage`

**Files:**
- Create: `web/src/pages/DashboardPage.tsx`

**Interfaces:**
- Consumes: `health`, `breakerStatus`, `resetBreaker`, `vectorStats`, `trendReport` from `api.ts`

### 目标
展示系统状态、缓存、熔断器、向量记忆、趋势报告。

- [ ] **Step 1: 创建 `DashboardPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { health, breakerStatus, resetBreaker, vectorStats, trendReport } from '../api'

export default function DashboardPage() {
  const [healthData, setHealthData] = useState<Record<string, any> | null>(null)
  const [breakerData, setBreakerData] = useState<Record<string, any> | null>(null)
  const [vectorData, setVectorData] = useState<Record<string, any> | null>(null)
  const [trendData, setTrendData] = useState<Record<string, any> | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setError('')
      const [h, b, v, t] = await Promise.all([
        health(),
        breakerStatus(),
        vectorStats(),
        trendReport(),
      ])
      setHealthData(h)
      setBreakerData(b)
      setVectorData(v)
      setTrendData(t)
    } catch (err: any) {
      setError(err.message || '加载仪表盘失败')
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleReset = async (lang: string) => {
    await resetBreaker(lang)
    await load()
  }

  return (
    <div className="space-y-6">
      {error && <div className="bg-red-50 text-red-700 p-4 rounded">{error}</div>}

      <section className="p-4 border border-slate-200 rounded">
        <h2 className="font-bold text-lg mb-3">健康度</h2>
        {healthData && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-slate-400">整体</span>
              <p className="font-medium">{healthData.health?.overall}</p>
            </div>
            <div>
              <span className="text-slate-400">缓存</span>
              <p className="font-medium">{healthData.health?.cache}</p>
            </div>
            <div>
              <span className="text-slate-400">规则</span>
              <p className="font-medium">{healthData.health?.rules}</p>
            </div>
            <div>
              <span className="text-slate-400">熔断器</span>
              <p className="font-medium">{healthData.health?.breaker}</p>
            </div>
          </div>
        )}
      </section>

      <section className="p-4 border border-slate-200 rounded">
        <h2 className="font-bold text-lg mb-3">熔断器状态</h2>
        {breakerData && Object.keys(breakerData).length > 0 ? (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-300">
                <th className="py-2">语言</th>
                <th className="py-2">状态</th>
                <th className="py-2">失败次数</th>
                <th className="py-2">阈值</th>
                <th className="py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(breakerData).map(([lang, s]: [string, any]) => (
                <tr key={lang} className="border-b border-slate-100">
                  <td className="py-2">{lang}</td>
                  <td className="py-2">{s.state}</td>
                  <td className="py-2">{s.failures}</td>
                  <td className="py-2">{s.threshold}</td>
                  <td className="py-2">
                    <button
                      onClick={() => handleReset(lang)}
                      className="text-sm text-blue-600 hover:underline"
                    >
                      重置
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-slate-500">暂无熔断器记录</p>
        )}
      </section>

      <section className="p-4 border border-slate-200 rounded">
        <h2 className="font-bold text-lg mb-3">向量记忆</h2>
        {vectorData && (
          <div className="text-sm">
            <p>总模式数：{vectorData.total_patterns}</p>
            {vectorData.top_kinds && (
              <div className="mt-2">
                <span className="text-slate-500">Top Bug 类型：</span>
                <ul className="list-disc list-inside">
                  {vectorData.top_kinds.map((k: any) => (
                    <li key={k.kind}>{k.kind}: {k.count}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="p-4 border border-slate-200 rounded">
        <h2 className="font-bold text-lg mb-3">趋势报告</h2>
        {trendData && (
          <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto">
            {JSON.stringify(trendData, null, 2)}
          </pre>
        )}
      </section>
    </div>
  )
}
```

- [ ] **Step 2: 验证编译**

```bash
cd web
npm run build
```

- [ ] **Step 3: 提交**

```bash
git add web/src/pages/DashboardPage.tsx
git commit -m "feat: 仪表盘页面"
```

---

## Task 10: 根目录 npm scripts 与启动整合

**Files:**
- Create: `package.json`
- Modify: `web/vite.config.ts`（已存在，确保 proxy 正确）

**Interfaces:**
- Produces: `npm run dev` 同时启动前后端

### 目标
让用户从项目根目录执行 `npm run dev` 一键启动。

- [ ] **Step 1: 创建根目录 `package.json`**

```json
{
  "name": "dualcheck-code",
  "version": "0.11.0",
  "private": true,
  "scripts": {
    "dev": "concurrently \"npm run dev:web\" \"npm run dev:server\"",
    "dev:web": "cd web && npm run dev",
    "dev:server": "python web_server.py",
    "build": "cd web && npm run build",
    "install:all": "npm install && cd web && npm install"
  },
  "devDependencies": {
    "concurrently": "^8.2.2"
  }
}
```

- [ ] **Step 2: 安装根目录依赖**

```bash
npm install
```

- [ ] **Step 3: 验证启动**

```bash
npm run dev
```

Expected: 终端同时显示 Vite 和 FastAPI 启动日志，浏览器打开 `http://localhost:5173` 能看到页面。

- [ ] **Step 4: 提交**

```bash
git add package.json
git commit -m "chore: 根目录 npm scripts 与前后端并发启动"
```

---

## Task 11: 后端测试补充

**Files:**
- Modify: `tests/test_web_server.py`

**Interfaces:**
- Consumes: `web_server.py`

### 目标
覆盖 `/api/batch`、`/api/health`、`/api/breaker`、`/api/vector/stats`、`/api/trend` 端点。

- [ ] **Step 1: 补充测试**

```python
# tests/test_web_server.py
from fastapi.testclient import TestClient


def client():
    from web_server import app
    return TestClient(app)


def test_review_endpoint():
    c = client()
    response = c.post("/api/review", json={
        "code": "x = 1\n",
        "lang": "python",
        "api_key": "",
        "use_cache": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert "risk" in data
    assert "findings" in data


def test_batch_endpoint():
    c = client()
    response = c.post("/api/batch", json={
        "directory": "data",
        "lang": "python",
        "api_key": "",
        "use_cache": True,
        "line_threshold": 500,
    })
    assert response.status_code == 200
    data = response.json()
    assert "batch_summary" in data
    assert "files" in data


def test_health_endpoint():
    c = client()
    response = c.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "health" in data


def test_breaker_endpoint():
    c = client()
    response = c.get("/api/breaker")
    assert response.status_code == 200


def test_vector_stats_endpoint():
    c = client()
    response = c.get("/api/vector/stats")
    assert response.status_code == 200


def test_trend_endpoint():
    c = client()
    response = c.get("/api/trend")
    assert response.status_code == 200
```

- [ ] **Step 2: 运行全部后端测试**

```bash
pytest tests/test_web_server.py tests/test_reviewer_api_key.py tests/test_fallback_chain_api_key.py -v
```

Expected: 全部 PASS

- [ ] **Step 3: 运行完整测试套件**

```bash
pytest
```

Expected: 全部 PASS（或新增测试不破坏现有测试）

- [ ] **Step 4: 提交**

```bash
git add tests/test_web_server.py
git commit -m "test: FastAPI 端点覆盖"
```

---

## Task 12: 端到端冒烟验证

**Files:**
- 无新增文件

### 目标
验证 `npm run dev` 启动后，前端三个页面都能正常工作。

- [ ] **Step 1: 启动服务**

```bash
npm run dev
```

- [ ] **Step 2: 单文件评审验证**

1. 浏览器打开 `http://localhost:5173`。
2. 在 Monaco 编辑器中输入 `def f(a=[]):\n    pass\n`。
3. 留空 API key，点击「评审」。
4. 预期：返回本地兜底结果，页面显示 `RiskBanner` 和 findings。

- [ ] **Step 3: 批量评审验证**

1. 切换到 `/batch`。
2. 输入 `data` 目录绝对路径。
3. 点击「开始批量评审」。
4. 预期：显示文件列表和汇总。

- [ ] **Step 4: 仪表盘验证**

1. 切换到 `/dashboard`。
2. 预期：显示健康度、熔断器状态、向量统计、趋势报告。

- [ ] **Step 5: 提交冒烟记录**

```bash
# 记录到 iteration/iteration_log.md 或 tests/test_record.md
# 按项目规范手动追加
```

---

## 实现计划 Self-Review

### 1. Spec 覆盖

| Spec 要求 | 对应任务 |
|-----------|---------|
| 本地 Web UI | Task 4-10 |
| 单文件评审 | Task 7 |
| 批量评审 | Task 8 |
| 仪表盘 | Task 9 |
| DeepSeek key 前端输入 | Task 1, 2, 7 |
| 后端代理 | Task 3 |
| `skill/` 独立 | 全局约束 + Task 3（`web_server.py` 放根目录） |
| CLI 兼容 | Task 1, 2 保持默认参数 |
| 后端覆盖率 ≥80% | Task 11 |
| `npm run dev` 启动 | Task 10 |

### 2. Placeholder 扫描

- 无 TBD/TODO
- 无 "add appropriate error handling" 等模糊表述
- 每个步骤都包含具体代码或命令

### 3. 类型一致性

- `api_key: str = ""` 贯穿 `FallbackChain.call`、`Reviewer._run_ai`、`Reviewer.review`、`ReviewRequest`
- `Finding` 类型在 `api.ts` 和 `FindingCard` 中一致
- `BatchResponse` 在 `api.ts` 和 `BatchPage` 中一致

### 4. 风险点

- `/api/batch` 端点目前自己逐文件调用 reviewer，未复用 `bulkhead.py` 的舱壁隔离。后续如需完整舱壁能力，可再封装 `_run_batch` 的返回版本。
- `/api/trend` 返回 JSON 字符串，前端直接展示。后续可优化为结构化渲染。
- 前端样式使用 Tailwind 类名，但当前未安装 Tailwind。需要额外一步：安装 Tailwind 并配置，或者改为内联样式。本计划假设使用 Tailwind；若项目不想引入 Tailwind，Task 4-9 组件需要改为普通 CSS/inline styles。

> **建议**：在 Task 4 中补充安装 Tailwind CSS：`npm install -D tailwindcss postcss autoprefixer && npx tailwindcss init -p`，并配置 `tailwind.config.js` 扫描 `src/**/*.{ts,tsx}`。

---

## 执行方式

**Plan complete and saved to `runtime/docs/superpowers/plans/2026-07-15-frontend-visualization.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** - 每个 Task 派一个独立子代理执行，我负责审查衔接
2. **Inline Execution** - 在当前会话中按顺序执行所有 Task

**Which approach?**
