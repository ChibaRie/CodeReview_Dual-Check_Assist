# 迭代 v0.10 — 代码质量重构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `app.py::review()` 拆分为 `Reviewer` 服务 + 提取 `config.py` 纯函数模块，外部 API/CLI/测试 100% 绿。

**Architecture:** 新增 `reviewer.py`（`Reviewer` 类，惰性持有 `_breaker_pool`，`review()` 拆成 8 个私有方法含 `_prepare` 第 0 步）与 `config.py`（4 个纯函数，逐字移植自 `app.py:58-78`）。`app.review`/`app.merge` 退化为薄转发到进程级 `Reviewer` 单例。config 每次 `review()` 调用重载、pool 惰性首建——逐字保留旧 quirk。

**Tech Stack:** Python 3.10+、pytest、stdlib（pathlib/dataclasses/json/re）。无新依赖。

## Global Constraints

- 现有 156 测试基线（`cd tests && python -m pytest -q` → `156 passed in 1.69s`）**全绿、0 fail / 0 error** 是每一步合并前置门。绿数下降即回到上一绿状态。
- **逐字移植**：复制中间步骤，不重写等效逻辑。`resolve_cache_dir` 的 `is_default` 反推分支（`cfg.resolve() == default_cfg`）原样保留——保守路线，零行为变化。
- `config_path` 留在 `Reviewer.review` 5 参里（与 `app.review` 同签名 `review(code, lang, framework="", config_path="", use_cache=True)`），不进 `__init__`。config 每次 `review()` 重载、pool 惰性首建，复刻旧 `_breaker_pool` `if _breaker_pool is None` quirk。
- **本轮不引入任何新 `try/except`**；不清理 `pool._save()` 私有直调与 `getattr(static_report, 'source_file', '')` 兜底（逐字照搬）。
- 不动 `tests/conftest.py`，不修原始测试，不引入 pytest markers / `--cov` 门槛。
- 提交消息用约定式格式（`chore:`/`refactor:`/`test:`/`docs:`）。

## 关键事实（已核实）

- **无 `tests/test_app.py`**：156 测试覆盖 `bulkhead`/`cqrs_router`/`circuit_breaker`/`fallback_chain`/`state_machine`/`static_check`/`trend_analyzer`/`vector_store`，**无任何测试直接 import `app.review` 或 `app.merge`**。
- **但 `app.py::main()` CLI 直接调用** `_load_config`/`_resolve_cache_dir`/`_default_config_path`/`_get_breaker_pool`（`app.py:514, 515, 519, 530, 531, 535, 553, 574, 585, 611`）——这些调用点必须在 Task 2 改名（`_load_config`→`load_config` 等）。
- `app.py::main()` 还用 `_get_breaker_pool(config, persist_path)`（旧模块级单例）在 `--breaker-reset`/`--breaker-status` 两处（`app.py:519, 535`）。Task 4 把 `_get_breaker_pool` 内部改为操作 `Reviewer` 单例的 `_breaker_pool`，保持 CLI 与 `review()` 共享单一 pool。
- **conftest 真实 fixture 名**（已核实）：`python_buggy_code` / `python_clean_code` / `java_code` / `go_issues_code` / `js_issues_code` / `go_code` / `temp_dir` / `temp_cache_dir` / `empty_code` / `unicode_code` / `very_large_code` / `special_chars_code` / `mock_http_success` / `mock_http_failure` / `mock_http_auth_error`。
- `app.py` 顶部已有模块级 `import argparse / json / re / sys / time`（`app.py:1-9`）——`reviewer.py` 顶部按同风格写模块级 `import json / re / time`。

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `skill/scripts/config.py` | **创建** | 4 个无状态纯函数：`load_config` / `default_config_path` / `resolve_cache_dir` / `model_ver`。仅依赖 stdlib。 |
| `skill/scripts/reviewer.py` | **创建** | `Reviewer` 类（`__init__` 无参惰性、`review()` 5 参 + 8 个私有方法）、`merge`/`_build_prompt`/`_parse_ai`/`_risk` 实例方法、`_get_default()` 无参单例。 |
| `skill/scripts/app.py` | **修改** | 删 4 个 `_` 配置私有函数 → `from config import ...`；删 `review()`/`merge()`/`_build_prompt`/`_parse_ai`/`_risk` 实现体 → 转发到 `reviewer`；保留 `AIReport`/`FinalReport` 数据类、`_get_breaker_pool`（内部改操作 Reviewer 单例）、CLI `_run_batch`/`main`/`_fmt`/`_fmt_perf`/`_smoke`。 |
| `tests/_snapshot_legacy.py` | **创建后删** | 一次性脚本，调旧 `app._resolve_cache_dir` 生成快照。Task 1 创建并运行，Task 1 末删除。 |
| `tests/fixtures/config_cache_dir.json` | **创建** | 快照 oracle（输入→输出映射）。 |
| `tests/test_config.py` | **创建** | `test_resolve_cache_dir_matches_snapshot`，parametrize 快照比对。 |
| `tests/test_reviewer.py` | **创建** | `TestReviewerConstruction`（惰性建池）+ `TestReviewForwardingParity`（`app.review`↔`Reviewer.review` parity）。 |

依赖方向：`app → reviewer → config → (stdlib)`，外加 `reviewer → app` 仅取数据类（`AIReport`/`FinalReport`）——通过 `app.py` import 顺序（先定义 dataclass 再 import reviewer）打破循环。

---

## Task 1: 固化 `resolve_cache_dir` 行为快照（重构前，oracle = 旧实现）

**目的**：在删除旧 `app._resolve_cache_dir` 之前，跑旧实现对一组固定输入产出快照 JSON。这是 Task 5 oracle 的唯一来源——切断自证循环。

**Files:**
- Create: `tests/_snapshot_legacy.py`
- Create: `tests/fixtures/config_cache_dir.json`
- Delete: `tests/_snapshot_legacy.py`（Step 6）

**Interfaces:**
- Consumes: `app._resolve_cache_dir`（重构前存在）、`app._default_config_path`（重构前存在）
- Produces: `tests/fixtures/config_cache_dir.json`（给 Task 5 作 oracle）

- [ ] **Step 1: 跑基线确认 156 全绿**

Run: `cd tests && python -m pytest -q`
Expected: `156 passed`（1.69s 左右）。若非 156 passed，**停止**，先排查环境。

- [ ] **Step 2: 确认 fixtures 目录**

Run: `mkdir -p tests/fixtures && echo ok`
Expected: `ok`

- [ ] **Step 3: 写一次性快照脚本**

Create `tests/_snapshot_legacy.py`:

```python
"""一次性脚本：调重构前的 app._resolve_cache_dir 固化行为快照。
跑完即删（Task 1 Step 6）。不要 import 入 conftest，不要纳入 pytest 收集。"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))
import app  # noqa: E402  重构前仍存在 _resolve_cache_dir / _default_config_path

default_cfg = app._default_config_path()
default_cfg_dir = str(Path(default_cfg).resolve().parent)

CASES = [
    # (cache_dir, config_path)
    ("C:/tmp/mcache", ""),           # 绝对路径 + 空 config
    ("/var/cache/dc", ""),           # 绝对路径 + 空 config
    ("data/.cache", ""),              # 相对 + 空 config（落 default base）
    ("dc_cache/sub", ""),             # 相对 + 空 config
    ("data/.cache", default_cfg),    # 相对 + 默认 config 显式传入
    ("data/.cache", str(Path(default_cfg_dir, "custom_config.json"))),  # 相对 + 自定义 config
    ("cc", str(Path(default_cfg_dir, "custom_config.json"))),          # 相对 + 自定义 config
    ("", ""),                         # 空 cache_dir + 空 config
    ("", default_cfg),               # 空 cache_dir + 默认 config
]


def main() -> None:
    out = []
    for cache_dir, config_path in CASES:
        result = app._resolve_cache_dir(cache_dir, config_path)
        out.append({"cache_dir": cache_dir, "config_path": config_path, "expected": result})
    target = Path(__file__).resolve().parent / "fixtures" / "config_cache_dir.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(out)} cases to {target}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行快照脚本生成 JSON**

Run: `cd tests && python _snapshot_legacy.py`
Expected: `wrote 9 cases to ...tests/fixtures/config_cache_dir.json`

- [ ] **Step 5: 肉眼核验快照内容合理**

Read `tests/fixtures/config_cache_dir.json`。手工核对 9 条记录：
- 绝对路径两条：`expected` 原样返回（`C:/tmp/mcache`、`/var/cache/dc`）
- `is_default` 分支成立的三条（`config_path=""` 两条 + `config_path=default_cfg` 一条）：`expected` 以 `skill/` 根为 base，后缀 `data/.cache` 或 `dc_cache/sub` 或 `data/.cache`
- 自定义 config 两条：base 为 `references/` 目录，后缀 `data/.cache` 或 `cc`
- 空 cache_dir 两条：落 `data/.cache` 默认

若不符预期，**停止**，先排查旧实现（此时旧实现还在，对照 `app.py:66-74` 读）。

- [ ] **Step 6: 删除一次性脚本，提交快照**

Run:
```bash
rm tests/_snapshot_legacy.py
git add tests/fixtures/config_cache_dir.json
git commit -m "chore: 固化 resolve_cache_dir 行为快照（重构前 oracle）"
```
Expected: commit 成功；`git status` 干净（`_snapshot_legacy.py` 未提交、已删）。

- [ ] **Step 7: 再跑基线确认未污染套件**

Run: `cd tests && python -m pytest -q`
Expected: `156 passed`。

---

## Task 2: 创建 `config.py`（逐字移植 4 个纯函数）

**目的**：把 `app.py:58-78` 的 4 个 `_` 配置函数逐字搬到新 `config.py`，去前导下划线。**逻辑零变更**。

**Files:**
- Create: `skill/scripts/config.py`
- Modify: `skill/scripts/app.py:55-78`（删 4 个函数 + 相关注释）、`app.py` 顶部 import、`app.py:193-196`、`app.py:514, 515, 530, 531, 553, 574, 585, 611`（CLI 调用点改名）

**Interfaces:**
- Consumes: 无（仅 stdlib）
- Produces: `config.load_config(path:str)->dict`、`config.default_config_path()->str`、`config.resolve_cache_dir(cache_dir:str, config_path:str)->str`、`config.model_ver(models:list[dict])->str`

- [ ] **Step 1: 写 `config.py`（逐字复制 `app.py:58-78`，去前导下划线）**

Create `skill/scripts/config.py`:

```python
"""配置加载与路径解析 —— 无状态纯函数（逐字移植自 app.py:58-78，去前导下划线）。"""
from __future__ import annotations
import json
from pathlib import Path


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def default_config_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "references" / "config.example.json")


def resolve_cache_dir(cache_dir: str, config_path: str) -> str:
    p = Path(cache_dir or "data/.cache")
    if p.is_absolute():
        return str(p)
    cfg = Path(config_path) if config_path else None
    default_cfg = Path(default_config_path()).resolve()
    is_default = cfg and cfg.exists() and cfg.resolve() == default_cfg
    base = Path(__file__).resolve().parents[2] if is_default or not (cfg and cfg.exists()) else cfg.resolve().parent
    return str(base / p)


def model_ver(models: list[dict]) -> str:
    return json.dumps(models, sort_keys=True)[:32]
```

**逐字移植纪律自检**：对照 `app.py:66-74` 旧实现，`p`/`cfg`/`default_cfg`/`is_default`/`base` 五个中间变量与判断顺序一字不改。`default_config_path` 用 `parents[1]`（`config.py` 与 `app.py` 同在 `skill/scripts/`，`parents[1]` 仍指向 `skill/`）。`resolve_cache_dir` 内 `parents[2]` 指 `skill/`，与旧 `app.py` 一致。

- [ ] **Step 2: 修改 `app.py` 顶部 import**

在 `app.py` 现有 import 块（`app.py:1-19`）末追加：

```python
from config import load_config, default_config_path, resolve_cache_dir, model_ver
```

- [ ] **Step 3: 删除 `app.py:55-78` 的 4 个旧私有函数连同分隔注释**

删除 `app.py` 中 `# ── 配置解析 ──` 分隔与其下 `_load_config`/`_default_config_path`/`_resolve_cache_dir`/`_model_ver` 四个函数体。

- [ ] **Step 4: 改名调用点 —— `review()` 内（3 处）**

`app.py:193-196`（配置加载）改为：
```python
    config = (
        load_config(config_path) if config_path and Path(config_path).exists()
        else load_config(default_config_path())
    )
```

`app.py:200` 改为：
```python
    cache_dir = resolve_cache_dir(cache_cfg.get("dir", "data/.cache"), config_path)
```

`app.py:201` 改为：
```python
    mver = model_ver(config.get("models", []))
```

- [ ] **Step 5: 改名调用点 —— `main()` CLI 内**

对 `app.py` 全文做**精确**的标识符全局替换（只改这 4 个，别误伤其它 `_` 私有符号如 `_get_breaker_pool`/`_build_prompt`/`_fmt` 等）：
- `_load_config` → `load_config`
- `_default_config_path` → `default_config_path`
- `_resolve_cache_dir` → `resolve_cache_dir`
- `_model_ver` → `model_ver`

调用点位置：`app.py:514, 515-516, 530, 531-532, 553, 574, 585, 611`。

- [ ] **Step 6: 跑测试确认全绿**

Run: `cd tests && python -m pytest -q`
Expected: `156 passed`。

- [ ] **Step 7: 跑 CLI 冒烟确认 main() 调用链通**

Run: `cd skill/scripts && python app.py --code-string "def f(a=[]): pass" --lang python --no-cache 2>&1 | head -20`
Expected: 输出含 `风险等级:` 与 `## 静态层`（不报 `NameError`/`ImportError`）。若报 `NameError: name '_resolve_cache_dir' is not defined`，回到 Step 5 查漏改名点。

- [ ] **Step 8: 提交**

```bash
git add skill/scripts/config.py skill/scripts/app.py
git commit -m "refactor: 提取 config.py（逐字移植 4 个配置纯函数，零行为变更）"
```

---

## Task 3: 创建 `reviewer.py` —— `Reviewer` 服务与 `review()` 8 步拆分（逐字移植）

**目的**：新建 `reviewer.py`，`Reviewer` 类把 `app.py::review()`（`app.py:165-290`，~125 行）逐字拆成 `__init__`（无参惰性）+ `review()`（5 参）+ 8 个私有方法（`_prepare`/`_read_cache`/`_get_breaker`/`_run_static`/`_vector_match`/`_run_ai`/`_merge_and_store`/`_done_perf`）+ `merge`/`_build_prompt`/`_parse_ai`/`_risk`（实例方法，从 `app.py:84-159` 逐字移植）。本任务**只新建**，不改 `app.py`——`app.review`/`app.merge` 仍指向旧实现，套件继续 156 绿。Task 4 才把 `app.py` 转发到本模块。

**8 步拆分对逐字移植的兑现方式**：每个私有方法体内是旧 `review()` 对应行的逐字片段，只是把"参数从外层显式传入"代替"闭包捕获局部变量"。`perf` dict 作为可变对象贯穿（与旧实现同一只 dict 语义一致），不复制。`_done_perf` 仅封装收尾 `elapsed_ms` 计算。

| 私有方法 | 旧 `app.py` 行 |
|---|---|
| `_prepare(config_path)` | `193-202, 214-217` |
| `_read_cache(key, cache_dir, cache_cfg, use_cache)` | `204-212` |
| `_get_breaker(pool, lang)` | `217-218` |
| `_run_static(code, lang, review_cfg)` | `221-227` |
| `_vector_match(static_report, code, cache_dir)` | `230-249` |
| `_run_ai(lang_breaker, static_report, code, lang, framework, config, pool)` | `262-270` |
| `_merge_and_store(static_report, ai_report, router, key, code, lang, cache_hit, vstore)` | `271-285` |
| `_done_perf(t_total, perf)` | `211, 284, 287` |

`review()` 主体目标 ~60 行：构造 perf → `_prepare` → `_read_cache`（命中即收尾 return）→ `_get_breaker` → `_run_static` → `_vector_match` → 状态机循环调 `_run_ai` / `_merge_and_store` → `_done_perf` → return。

**Files:**
- Create: `skill/scripts/reviewer.py`

**Interfaces:**
- Consumes: `from config import load_config, default_config_path, resolve_cache_dir, model_ver`（Task 2 产出）；`from static_check import static_check, Finding, StaticReport`；`from cqrs_router import CQRSRouter, make_key`；`from circuit_breaker import BreakerPool, create_pool`；`from fallback_chain import FallbackChain, ModelConfig, ChainResult`；`from state_machine import initial_state, is_terminal, next_state`；`from vector_store import VectorStore, PatternMatch`；`from app import AIReport, FinalReport`（数据类归属见下）。
- Produces: `reviewer.Reviewer` 类、`reviewer._get_default()->Reviewer`

**数据类归属与循环 import**：`AIReport`/`FinalReport` 保留在 `app.py`（被 `_fmt`/`_run_batch` 引用）。`reviewer.py` 顶部 `from app import AIReport, FinalReport`——**唯一 reviewer→app 反向依赖**。为避免循环 import：`app.py` 必须先定义 `AIReport`/`FinalReport`（`app.py:39-52`）**再** `from reviewer import ...`（Task 4 Step 1 保证此顺序）。本任务写 `reviewer.py` 时信任此约定。

- [ ] **Step 1: 写 `reviewer.py` —— 顶部模块级 import + `Reviewer.__init__` + `_prepare`**

Create `skill/scripts/reviewer.py`:

```python
"""Reviewer 服务：编排 review() 双检流程。逐字移植自 app.py:165-290。"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

from app import AIReport, FinalReport
from circuit_breaker import BreakerPool, create_pool
from config import default_config_path, load_config, model_ver, resolve_cache_dir
from cqrs_router import CQRSRouter, make_key
from fallback_chain import ChainResult, FallbackChain, ModelConfig
from state_machine import initial_state, is_terminal, next_state
from static_check import Finding, StaticReport, static_check
from vector_store import PatternMatch, VectorStore

_SOURCE_DELIM = "__AI_DUAL_CHECK_SOURCE__"


class Reviewer:
    def __init__(self) -> None:
        self._breaker_pool: BreakerPool | None = None

    def _prepare(self, config_path: str) -> tuple[dict, str, str, BreakerPool]:
        cfg = (
            load_config(config_path) if config_path and Path(config_path).exists()
            else load_config(default_config_path())
        )
        cache_cfg = cfg.get("cache", {})
        cache_dir = resolve_cache_dir(cache_cfg.get("dir", "data/.cache"), config_path)
        persist_path = str(Path(cache_dir) / ".breaker_state.json")
        if self._breaker_pool is None:
            self._breaker_pool = create_pool(cfg, persist_path)
        return cfg, cache_dir, persist_path, self._breaker_pool
```

**逐字移植自检**（对照旧 `app.py:193-217`）：`cfg = ... if ... else ...` 三元、`cache_cfg.get("dir", "data/.cache")` 默认值、`persist_path` 拼接、`if self._breaker_pool is None` 惰性建池——逐字。唯一非逐字改动是 `_breaker_pool` 从模块级变实例级（spec §5.4 明确认可）。

- [ ] **Step 2: 加 `_build_prompt` / `_parse_ai` / `_risk` / `merge`（实例方法，逐字移植 `app.py:84-159`）**

Append to `reviewer.py`（`Reviewer` 类内）:

```python
    def _build_prompt(self, static_report: StaticReport, code: str, lang: str, framework: str) -> str:
        findings_text = "\n".join(f"- 行 {f.line} [{f.kind}] {f.message}" for f in static_report.findings)
        escaped = code.replace(_SOURCE_DELIM, f"{_SOURCE_DELIM}_ESCAPED")
        source_block = f"{_SOURCE_DELIM}\n{escaped}\n{_SOURCE_DELIM}"
        return (
            "你是一位资深代码评审员。请基于以下静态快检结果和源代码，做语义深检。\n\n"
            f"语言: {lang}\n框架: {framework or '无'}\n\n"
            "静态快检发现的问题（可能包含误报）：\n" + (findings_text or "无") + "\n\n"
            "源代码：\n" + source_block + "\n\n"
            "请严格按以下 JSON 格式返回，不要包含任何 markdown 代码块标记：\n"
            '{"confirmation": [{"line": 行号, "kind": "类型", "severity": "high/medium/low", "message": "确认说明"}], '
            '"rejection": [{"line": 行号, "kind": "类型", "severity": "low", "message": "认为是误报的理由"}], '
            '"new_findings": [{"line": 行号, "kind": "类型", "severity": "high/medium/low", "message": "AI 发现静态层漏掉的问题"}]}\n'
        )

    def _parse_ai(self, text: str) -> AIReport | None:
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        raw = m.group(1).strip() if m else text.strip()
        try:
            data = json.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None

        def to_findings(xs: list[dict]) -> list[Finding]:
            return [
                Finding(x.get("line", 0), x.get("kind", ""), x.get("severity", "low"), x.get("message", ""))
                for x in xs
            ]

        return AIReport(
            confirmation=to_findings(data.get("confirmation", [])),
            rejection=to_findings(data.get("rejection", [])),
            new_findings=to_findings(data.get("new_findings", [])),
        )

    def _risk(self, ai_report: AIReport | None, static: StaticReport) -> str:
        high = sum(1 for f in static.findings if f.severity == "high")
        if ai_report:
            high += sum(1 for f in ai_report.new_findings if f.severity == "high")
            high += sum(1 for f in ai_report.confirmation if f.severity == "high")
        if high > 0:
            return "阻止合并"
        if static.findings or (ai_report and (ai_report.confirmation or ai_report.new_findings)):
            return "修复后合并"
        return "可合并"

    def merge(self, static_report: StaticReport, ai_report: AIReport | None) -> FinalReport:
        rows: list[dict] = [
            {"line": f.line, "layer": "static", "kind": f.kind, "severity": f.severity, "message": f.message}
            for f in static_report.findings
        ]
        if ai_report:
            rows = rows + [
                {"line": f.line, "layer": "ai_confirmed", "kind": f.kind, "severity": f.severity, "message": f.message}
                for f in ai_report.confirmation
            ]
            rows = rows + [
                {"line": f.line, "layer": "ai_new", "kind": f.kind, "severity": f.severity, "message": f.message}
                for f in ai_report.new_findings
            ]
            ai_summary = (
                f"AI 确认 {len(ai_report.confirmation)} 条，新发现 {len(ai_report.new_findings)} 条，"
                f"否定 {len(ai_report.rejection)} 条"
            )
        else:
            ai_summary = "AI 深检未运行（熔断降级或模型链全部失败）"
        risk = self._risk(ai_report, static_report)
        summary = f"风险等级: {risk}; 静态问题 {len(static_report.findings)} 条"
        if ai_report:
            summary += f"; AI 新发现 {len(ai_report.new_findings)} 条"
        return FinalReport(risk=risk, summary=summary, static_summary=static_report.summary, ai_summary=ai_summary, findings=rows)
```

**逐字移植自检**：`_parse_ai` 用模块级 `re`/`json`（旧 `app.py:100-120` 也用模块级）。`merge` 内 `rows = rows + [...]` 两处拼接原样（旧 `app.py:141, 145` 不用 `extend`）。`_risk` 内 `high` 累加顺序：先 static high、再 new、再 confirmed（与旧 `app.py:124-127` 一致）。

- [ ] **Step 3: 加 7 个评审管线私有方法（`_read_cache`/`_get_breaker`/`_run_static`/`_vector_match`/`_run_ai`/`_merge_and_store`/`_done_perf`）—— 逐字移植 `app.py:165-290` 对应片段**

Append to `reviewer.py`（`Reviewer` 类内）。**每个方法体是旧 `review()` 对应行的逐字片段，参数从外层传入**：

```python
    def _read_cache(self, key: str, cache_dir: str, cache_cfg: dict, use_cache: bool
                    ) -> tuple[FinalReport | None, float, CQRSRouter | None]:
        """逐字移植 app.py:204-212。返回 (命中报告|None, cache_lookup_ms, router)。
        router 传出供未命中路径复用（保持旧单一 router 语义）。"""
        router: CQRSRouter | None = None
        lookup_ms = 0.0
        if use_cache:
            router = CQRSRouter(cache_dir, cache_cfg.get("ttl_days", 7))
            t_cache = time.perf_counter()
            cached = router.try_read(key)
            lookup_ms = (time.perf_counter() - t_cache) * 1000
            if cached:
                return FinalReport(**cached), lookup_ms, router
        return None, lookup_ms, router

    def _get_breaker(self, pool: BreakerPool, lang: str):
        """逐字移植 app.py:217-218。"""
        lang_breaker = pool.get(lang)
        return lang_breaker, lang_breaker.state

    def _run_static(self, code: str, lang: str, review_cfg: dict) -> StaticReport:
        """逐字移植 app.py:221-227。"""
        return static_check(
            code, lang,
            max_function_lines=review_cfg.get("max_function_lines", 50),
            max_nesting=review_cfg.get("max_nesting", 4),
            max_line_length=review_cfg.get("max_line_length", 120),
        )

    def _vector_match(self, static_report: StaticReport, code: str, cache_dir: str
                      ) -> tuple[int, dict | None, VectorStore]:
        """逐字移植 app.py:230-249。返回 (vector_matches, vector_top_match, vstore)。
        vstore 随方法传出——调用方负责 close()（保留旧生命周期）。"""
        vector_db = str(Path(cache_dir) / "patterns.db")
        vstore: VectorStore | None = VectorStore(vector_db)
        vector_matches = 0
        vector_top_match: dict | None = None
        for sf in static_report.findings:
            snippet = "\n".join(code.splitlines()[max(0, sf.line - 2): sf.line + 1])
            matches = vstore.search(kind=sf.kind, snippet=snippet, threshold=0.55, limit=1)
            if matches:
                vector_matches += 1
                if vector_top_match is None or matches[0].combined_sim > (
                    vector_top_match.get("similarity", 0) if vector_top_match else 0
                ):
                    m = matches[0]
                    vector_top_match = {
                        "kind": m.pattern.kind,
                        "message": m.pattern.message,
                        "fix_hint": m.pattern.fix_hint,
                        "similarity": round(m.combined_sim, 2),
                        "source_file": m.pattern.source_file,
                        "days_ago": round((time.time() - m.pattern.created_at) / 86400, 1),
                    }
        return vector_matches, vector_top_match, vstore

    def _run_ai(self, lang_breaker, static_report: StaticReport, code: str, lang: str,
                framework: str, config: dict, pool: BreakerPool
                ) -> tuple[AIReport | None, str, str]:
        """逐字移植 app.py:262-270。返回 (ai_report, ai_tier, new_breaker_state)。"""
        prompt = self._build_prompt(static_report, code, lang, framework)
        chain = FallbackChain(
            [ModelConfig(**m) for m in config.get("models", [])], lang_breaker
        )
        chain_result: ChainResult = chain.call(prompt, static_report)
        ai_tier = chain_result.tier
        new_state = lang_breaker.state
        pool._save()  # 逐字保留私有直调（本轮不清理）
        ai_report = self._parse_ai(chain_result.text)
        return ai_report, ai_tier, new_state

    def _merge_and_store(self, static_report: StaticReport, ai_report: AIReport | None,
                         router: CQRSRouter | None, key: str, code: str, lang: str,
                         cache_hit: bool, vstore: VectorStore
                         ) -> tuple[FinalReport, int]:
        """逐字移植 app.py:271-285。返回 (report, vector_stored)。vstore 由调用方 close()。"""
        report = self.merge(static_report, ai_report)
        if router:
            code_lines = code.count("\n") + 1
            router.write(key, report.__dict__, lang=lang, code_lines=code_lines)
        vector_stored = 0
        if not cache_hit:
            source_file = getattr(static_report, 'source_file', '') or ''  # 逐字保留兜底
            imported = vstore.add_from_report(report.__dict__, code, lang, source_file)
            if imported > 0:
                vector_stored = imported
        return report, vector_stored

    def _done_perf(self, t_total: float, perf: dict) -> dict:
        """收尾 perf['elapsed_ms']（逐字保留旧 app.py:211, 284, 287 计算）。"""
        perf["elapsed_ms"] = (time.perf_counter() - t_total) * 1000
        return perf
```

**逐字移植自检清单**（对照旧 `app.py:165-290`）：
- `_read_cache`：`cache_cfg.get("ttl_days", 7)`、`t_cache`→`lookup_ms` 计算、命中 `FinalReport(**cached)` 拆包——逐字。`router` 传出以保持旧单一 router（旧命中分支不再用 router 但无副作用、未命中路径复用同一 router）。
- `_vector_match`：`snippet = "\n".join(code.splitlines()[max(0, sf.line - 2): sf.line + 1])`、`threshold=0.55, limit=1`、`days_ago` 计算——逐字。
- `_run_ai`：`pool._save()` 私有直调保留。
- `_merge_and_store`：`getattr(static_report, 'source_file', '')` 兜底保留；`code.count("\n") + 1` 行数计算逐字。
- `PatternMatch` import：Step 1 顶部已 `from vector_store import PatternMatch, VectorStore`。

- [ ] **Step 4: 加 `review()` 主体 —— 串联 8 个私有方法（目标 ~60 行）**

Append to `reviewer.py`（`Reviewer` 类内）:

```python
    def review(self, code: str, lang: str, framework: str = "",
               config_path: str = "", use_cache: bool = True
               ) -> tuple[FinalReport, dict]:
        perf: dict = {
            "cache_hit": False,
            "elapsed_ms": 0.0,
            "cache_lookup_ms": 0.0,
            "ai_tier": "none",
            "breaker_state": "CLOSED",
            "vector_matches": 0,
            "vector_top_match": None,
            "vector_stored": 0,
        }
        t_total = time.perf_counter()

        config, cache_dir, persist_path, pool = self._prepare(config_path)
        cache_cfg = config.get("cache", {})
        mver = model_ver(config.get("models", []))
        key = make_key(code, lang, mver)

        cached, lookup_ms, router = self._read_cache(key, cache_dir, cache_cfg, use_cache)
        perf["cache_lookup_ms"] = lookup_ms
        if cached is not None:
            perf["cache_hit"] = True
            return cached, self._done_perf(t_total, perf)

        lang_breaker, breaker_state = self._get_breaker(pool, lang)
        perf["breaker_state"] = breaker_state

        review_cfg = config.get("review", {})
        static_report = self._run_static(code, lang, review_cfg)

        vm, vtm, vstore = self._vector_match(static_report, code, cache_dir)
        perf["vector_matches"] = vm
        perf["vector_top_match"] = vtm

        state = initial_state()
        ai_report: AIReport | None = None
        while not is_terminal(state):
            state, action = next_state(state, "")
            if action == "run_static":
                continue
            if action == "check_gate":
                event = "allowed" if lang_breaker.allow() else "blocked"
                state, action = next_state(state, event)
            if action == "run_ai":
                ai_report, ai_tier, new_state = self._run_ai(
                    lang_breaker, static_report, code, lang, framework, config, pool
                )
                perf["ai_tier"] = ai_tier
                perf["breaker_state"] = new_state
            if action in ("merge_normal", "merge_degraded"):
                report, vector_stored = self._merge_and_store(
                    static_report, ai_report, router, key, code, lang, perf["cache_hit"], vstore
                )
                perf["vector_stored"] = vector_stored
                if vstore:
                    vstore.close()
                return report, self._done_perf(t_total, perf)

        if vstore:
            vstore.close()
        return self.merge(static_report, None), self._done_perf(t_total, perf)
```

**与旧实现的逐字对照自检**：
- `perf` 初值 dict 8 键顺序 = 旧 `app.py:181-190` ✓
- 命中分支 `return cached, self._done_perf(...)` 等价旧 `return FinalReport(**cached), perf` + `perf["elapsed_ms"]` 赋值（`_done_perf` 就是那行赋值的封装）✓
- `router` 由 `_read_cache` 传出，主体不再建——与旧 `app.py:204-205` 单一 router 语义一致 ✓
- 状态机循环 `if action == "run_static": continue`、`check_gate` event、`run_ai`、`merge_*`——逐字 = 旧 `app.py:254-285` ✓
- 终态 `return self.merge(static_report, None), self._done_perf(...)` = 旧 `app.py:290` `return merge(static_report, None), perf`（旧此处 `perf["elapsed_ms"]` 在 `app.py:287` 已赋值）✓

- [ ] **Step 5: 加 `_get_default()` 无参单例**

Append to `reviewer.py`（模块级，类外）:

```python
_default: Reviewer | None = None


def _get_default() -> Reviewer:
    global _default
    if _default is None:
        _default = Reviewer()
    return _default
```

- [ ] **Step 6: 跑测试（应仍 156——本任务只新建，app.review 仍指向旧实现）**

Run: `cd tests && python -m pytest -q`
Expected: `156 passed`。

注：本步不验证 `reviewer.py` 正确性（Task 5 加 parity 测试才验证）。只验证"新建模块未破坏现有套件"。若报 `ImportError`，多半是 `reviewer.py` 顶部 `from app import AIReport, FinalReport` 触发循环 import（`app` 此时还未 `from reviewer import`，应该不会循环——但若 `app.py` 内某处已先 import 了 `reviewer` 则会）——若循环，回 Task 4 Step 1 理顺顺序，或临时在 `reviewer.py` 顶部用延迟导入（函数体内 `from app import AIReport`），但**优先**靠 Task 4 的 import 顺序解决。

- [ ] **Step 7: 手测 `Reviewer.review` 一次（验证 reviewer 能独立跑通，用 mock HTTP）**

Run:
```bash
cd skill/scripts && python -c "
from unittest.mock import patch
sample = b'{\"confirmation\": [], \"rejection\": [], \"new_findings\": []}'
fake = type('R', (), {'read': lambda self: sample, 'status': 200, '__enter__': lambda s: s, '__exit__': lambda s, *a: None})()
with patch('urllib.request.urlopen', return_value=fake):
    from reviewer import Reviewer
    r, p = Reviewer().review('def f(a=[]): pass', 'python', use_cache=False)
    print(r.risk, round(p['elapsed_ms'], 1))
"
```
Expected: 输出形如 `修复后合并 123.4`（不报异常）。若 `ImportError`/`AttributeError`——对照 `app.py` 旧 `review()` 调用点检查 `reviewer.py` 各私有方法签名与内部调用。

- [ ] **Step 8: 提交**

```bash
git add skill/scripts/reviewer.py
git commit -m "refactor: 引入 Reviewer 服务（逐字移植 review/merge，8 步拆分）"
```

---

## Task 4: `app.py` 转发到 `Reviewer`，删旧实现体

**目的**：把 `app.py` 里的 `review()`/`merge()`/`_build_prompt()`/`_parse_ai()`/`_risk()` 旧实现体替换为转发到 `_get_default()`；`_get_breaker_pool` 内部改操作 `Reviewer` 单例的 `_breaker_pool`，使 CLI 与 `review()` 共享单 pool。数据类 `AIReport`/`FinalReport` 保留。CLI 与 `_run_batch`/`_smoke` 调用点不改（仍调 `app.review`/`app.merge`，透明）。

**Files:**
- Modify: `skill/scripts/app.py`（删 `review`/`merge`/`_build_prompt`/`_parse_ai`/`_risk` 实现体、改 `_get_breaker_pool`、加 import `reviewer`）

**Interfaces:**
- Consumes: `reviewer._get_default`, `reviewer.Reviewer`（Task 3 产出）
- Produces: 维持 `app.review`/`app.merge` 公共符号（5 参透传）；`_get_breaker_pool(config, persist_path)` 行为兼容

- [ ] **Step 1: `app.py` import `reviewer` —— 必须在 dataclass 定义之后**

确认 `app.py` 结构顺序：顶部 import 块（`app.py:1-19` + Task 2 加的 `from config import ...`）→ 模块级 `_breaker_pool`/`_get_breaker_pool`（`app.py:21-33`）→ **`AIReport`/`FinalReport` dataclass（`app.py:36-52`）** → 然后**才**加：

```python
from reviewer import _get_default, Reviewer
```

放在 `FinalReport` dataclass 之后那行（即 `app.py:52` 之后、`# ── 配置解析 ──` 原位置之前——Task 2 已删配置解析块）。这样 `reviewer` import 时 `AIReport`/`FinalReport` 已定义，避免循环 import。

- [ ] **Step 2: 删 `app.py` 的 `_build_prompt`/`_parse_ai`/`_risk`/`merge` 实现体**（`app.py:81-159`）

删除这 4 个函数整段（含 `# ── 提示词构建 / AI 解析 / 合并 ──` 分隔）。已核实无测试与 CLI 直接 import 这 4 个私有符号——纯删除不转发。若 `git grep` 发现引用（Step 6 自检），补一行 `from reviewer import _build_prompt as _build_prompt` 等（但 `reviewer.py` 这 4 个是实例方法，不是模块级——若需转发要改成模块级包装或导出 `Reviewer` 实例方法，预计无引用）。

- [ ] **Step 3: 删 `app.py` 的 `review()` 实现体与 `_SOURCE_DELIM`，替换为 5 参薄转发**

删除：
- `_SOURCE_DELIM = "__AI_DUAL_CHECK_SOURCE__"`（已搬入 `reviewer.py`）
- `review()` 旧实现体 125 行（`app.py:165-290`）

新增 5 参转发：

```python
def review(code, lang, framework="", config_path="", use_cache=True):
    return _get_default().review(code, lang, framework, config_path, use_cache)


def merge(static_report, ai_report):
    return _get_default().merge(static_report, ai_report)
```

- [ ] **Step 4: 改写 `_get_breaker_pool` —— 操作 `Reviewer` 单例的 `_breaker_pool`，删除模块级 `_breaker_pool` 字段**

删除模块级字段：
```python
_breaker_pool: BreakerPool | None = None   # 删此行
```

改 `_get_breaker_pool`（旧 `app.py:28-33`）为：

```python
def _get_breaker_pool(config: dict, persist_path: str = "") -> BreakerPool:
    """CLI --breaker-* 入口：确保 Reviewer 单例的 pool 已用 (config, persist_path) 初始化。
    review() 走 _prepare 时见 _breaker_pool 非空直接复用——CLI 与 review 共享单一 pool。"""
    rev = _get_default()
    if rev._breaker_pool is None:
        rev._breaker_pool = create_pool(config, persist_path)
    return rev._breaker_pool
```

删函数体内 `global _breaker_pool`。`create_pool` 与 `BreakerPool` 顶部 import 已存在（`app.py:12`）。

**语义核对**：旧的 `app._breaker_pool`（CLI 与 review 共享同一模块级单例）→ 新的 `Reviewer._breaker_pool`（CLI 经 `_get_breaker_pool` 写入、review 经 `_prepare` 复用，仍单一 pool）。CLI 首次跑 `--breaker-status` 用 CLI 的 `(config, persist_path)` 建 pool；后续 `review()` 的 `_prepare` 见 `_breaker_pool is not None` 直接复用——等价旧行为。

- [ ] **Step 5: 跑测试确认 156 全绿**

Run: `cd tests && python -m pytest -q`
Expected: `156 passed`。

- [ ] **Step 6: 跑 CLI 全套冒烟（验证 main 调用链 + breaker 管理 + 转发）**

Run（依次）:
```bash
cd skill/scripts
python app.py --code-string "def f(a=[]): pass" --lang python --no-cache | head -5
python app.py --breaker-status
python app.py --smoke
python app.py --health
```
Expected:
- 第 1 条输出含 `风险等级:`、`## 静态层`
- 第 2 条输出熔断器表头或 `无熔断器记录（尚未评审任何代码）`
- 第 3 条输出 `app smoke PASS: ...`
- 第 4 条输出健康度

若 `--breaker-status` 报 `AttributeError: 'Reviewer' object has no attribute '_breaker_pool'`——回 Task 3 检查 `__init__` 实例属性初始化。

**git grep 自检**确认无 packager/文档引用被删私有符号：
```bash
git grep -n "from app import _build_prompt\|from app import _parse_ai\|from app import _risk\|app\._build_prompt\|app\._parse_ai\|app\._risk"
```
Expected: 空（无引用）。若非空，补对应转发（但预计无引用——已核实 156 测试不 import 这 4 个）。

- [ ] **Step 7: 提交**

```bash
git add skill/scripts/app.py
git commit -m "refactor: app.review/merge 转发 Reviewer 单例，CLI 共享单一 breaker pool"
```

---

## Task 5: 新增 `test_config.py` 与 `test_reviewer.py`

**目的**：覆盖本轮纯新代码——`config.resolve_cache_dir` 逐字移植等价（oracle = Task 1 快照）+ `Reviewer` 构造与惰性建池 + `app.review`↔`Reviewer.review` parity。**现有 156 测试不动**。

**Files:**
- Create: `tests/test_config.py`
- Create: `tests/test_reviewer.py`

**Interfaces:**
- Consumes: `config.resolve_cache_dir`（Task 2）；`reviewer.Reviewer`（Task 3）；`app.review`（Task 4）；`tests/fixtures/config_cache_dir.json`（Task 1）；`conftest` 的 `mock_http_success` / `python_buggy_code` 既有 fixtures

- [ ] **Step 1: 写 `test_config.py` —— parametrize 快照比对**

Create `tests/test_config.py`:

```python
"""config 纯函数逐字移植等价 —— oracle = fixtures/config_cache_dir.json（重构前旧实现快照）。"""
import json
from pathlib import Path

import pytest

from config import resolve_cache_dir

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "config_cache_dir.json"


def _load_cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: f"cd={c['cache_dir']!r},cp={c['config_path']!r}")
def test_resolve_cache_dir_matches_snapshot(case):
    result = resolve_cache_dir(case["cache_dir"], case["config_path"])
    assert result == case["expected"], (
        f"resolve_cache_dir({case['cache_dir']!r}, {case['config_path']!r}) "
        f"= {result!r}, 快照期望 {case['expected']!r}（移植漂移）"
    )
```

**注**：`_load_cases()` 在模块加载期被 parametrize 调用。fixture 文件须存在（Task 1 已建）；若缺失，`_load_cases()` 抛 `FileNotFoundError`——真信号，不要 catch。无需 import `sys`/`sys.path` 操作——`conftest.py:14-16` 已在 collection 期把 `skill/scripts` 注入 `sys.path`，`from config import` 直接可用。

- [ ] **Step 2: 跑 `test_config.py` 应全绿**

Run: `cd tests && python -m pytest test_config.py -v`
Expected: `9 passed`（9 个 parametrize 用例）。

- [ ] **Step 3: 写 `test_reviewer.py` —— 构造/惰性建池 + parity**

Create `tests/test_reviewer.py`:

```python
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
```

**注**：
- `import app` / `from reviewer import Reviewer` 无需 `sys.path` 操作——`conftest.py:14-16` 已注入。
- parity 测试用 inline mock（`patch("urllib.request.urlopen", ...)`），不依赖 `conftest` 的 `mock_http_success` fixture，理由是守则"不动 conftest.py" + inline 最自包含。
- `test_prepare_lazy_builds_pool` 直接调 `_prepare("")`（私有方法）—— §7.3 守则"不 mock 私有方法"的例外：仅验建池副作用、不依赖网络。`_prepare` 契约本身就是"加载 config + 建池"，验它比走 full review 更聚焦。

- [ ] **Step 4: 跑新增测试应绿**

Run: `cd tests && python -m pytest test_config.py test_reviewer.py -v`
Expected: 9（config）+ 3（reviewer: 2 构造 + 1 parity）= `12 passed`。

- [ ] **Step 5: 跑全量确认 156 + 新增全绿**

Run: `cd tests && python -m pytest -q`
Expected: `168 passed`（156 + 12），0 fail / 0 error。

- [ ] **Step 6: 提交**

```bash
git add tests/test_config.py tests/test_reviewer.py
git commit -m "test: 新增 config 快照等价 + Reviewer 构造/parity 单测"
```

---

## Task 6: 文档同步 —— iteration_log 第 8 轮 + README 版本号

**目的**：补 `iteration/iteration_log.md` 第 8 轮记录（5 步法），README 版本号升 v0.10.0。

**Files:**
- Modify: `iteration/iteration_log.md`
- Modify: `README.md`（版本号处）

**Interfaces:** 无

- [ ] **Step 1: 读 `iteration/iteration_log.md` 末尾格式**

Run（看既有第 7 轮格式，沿用其标题层级与 emoji 风格写第 8 轮）: `tail -60 iteration/iteration_log.md`

- [ ] **Step 2: 追加第 8 轮记录**

Append to `iteration/iteration_log.md`:

```markdown
---

## 迭代 8（v0.10.0）— 代码质量重构：review() 拆分 + config 模块提取

**日期**：2026-07-12

### 痛点
`app.py::review()` ~125 行承担配置加载/缓存/熔断/静态/向量/AI/合并/写入全部职责；`_default_config_path` 硬编码；`_resolve_cache_dir` 反推 base 绕；模块级 `_breaker_pool` 单例 + global。代码质量与其"评审代码"定位形成讽刺，阻碍第 9 轮静态深度提升。

### 量化
- `review()` 函数体 125 行（>50 行上限 2.5 倍）
- 配置路径硬编码点 2 处（`_default_config_path`、`_resolve_cache_dir` 内 base 反推）
- 模块级 global 1 处（`_breaker_pool`）

### 根因
单文件 `app.py` 同时承担 CLI、编排、配置、格式化四职，无模块边界；review() 把"配置存活期"与"评审流程"耦合。

### 方案
- 提取 `config.py`（4 纯函数，逐字移植，零行为变更）
- 引入 `reviewer.py` `Reviewer` 服务：惰性建池、`review()` 8 步拆分（`_prepare` 第 0 步封装 config 加载）
- `app.review`/`app.merge` 薄转发；`_get_breaker_pool` 改操作 `Reviewer._breaker_pool`，CLI 与 review 共享单一 pool 单例
- Oracle 陷阱修正：重构前用旧 `app._resolve_cache_dir` 生成快照 JSON 作移植等价 oracle，切断自证循环

### 度量
- 现有 156 测试 100% 绿（前置门达成）
- 新增 `test_config.py`（9 用例）+ `test_reviewer.py`（2 构造 + 1 parity）
- `review()` 主体 ~50 行 + 8 个单一职责私有方法各 <25 行
- 零新 `try/except`，逐字移植纪律达成
```

- [ ] **Step 3: README 版本号升 v0.10.0**

Run: `grep -n "v0\.9" README.md | head -10`
把 `v0.9.2`（标题/徽章/badges/简介中出现的版本字面量）升为 `v0.10.0`。**只改版本号字面量**，不动功能描述（本轮是内部重构、无新功能）。若 README 有"近期变更"/"迭代历史"小节，追加一行 v0.10.0 摘要（中等重构、外部 API/CLI/测试兼容）。

- [ ] **Step 4: 跑全量回归最终确认**

Run: `cd tests && python -m pytest -q`
Expected: `168 passed`，0 fail / 0 error。

- [ ] **Step 5: 提交**

```bash
git add iteration/iteration_log.md README.md
git commit -m "docs: iteration_log 第 8 轮 + README v0.10.0"
```

---

## 完成判据（合并前必达）

- [ ] `cd tests && python -m pytest -q` → `168 passed`（156 + 12 新增），0 fail / 0 error
- [ ] `cd skill/scripts && python app.py --smoke` 输出 `app smoke PASS`
- [ ] `python app.py --breaker-status` 不报错
- [ ] `python app.py --health` 不报错
- [ ] `git log --oneline` 含 6 条新 commit（chore 快照 / refactor config / refactor reviewer / refactor 转发 / test 新测 / docs）
- [ ] `review()` 在 `reviewer.py` 内、`app.review` 转发、CLI 与 review 共享单 pool 单例
- [ ] `resolve_cache_dir` / `model_ver` / `load_config` / `default_config_path` 4 函数在 `config.py`、`app.py` 无同名旧私有
- [ ] 无新 `try/except`

## 下轮预告（不在本计划）

第 9 轮：Java/Go/JS 静态深度提升 + Java `hardcoded_secret` 误报修复。本计划清理后的 `Reviewer` 管线为其扫清障碍。