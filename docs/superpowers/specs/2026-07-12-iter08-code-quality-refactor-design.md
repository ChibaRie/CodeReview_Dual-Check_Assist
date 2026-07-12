# 迭代 v0.10 — 代码质量重构（review() 拆分 + config 模块提取）

- **版本**：v0.10.0（非破坏性内部重构；外部 API 字节兼容）
- **日期**：2026-07-12
- **迭代轮次**：第 8 轮（承接 v0.9.2）
- **本轮目标**：清理 `app.py::review()` 过长、配置路径硬编码、熔断器模块级单例耦合——为下一轮"静态分析深度提升"扫清管线障碍
- **不在本轮**：Java/Go/JS 静态深度、AST 规则、Java `hardcoded_secret` 误报修复（留待第 9 轮）

## 1. 背景与痛点

`skill/scripts/app.py::review()`（`app.py:165-290`，约 125 行）承担配置加载、CQRS 缓存读、熔断器获取、静态快检、向量记忆搜索、状态机驱动 AI 链路、合并、缓存写、向量库存储——职责过度集中。配套问题：

- `_default_config_path()` 硬指 `references/config.example.json`（`app.py:62-63`）
- `_resolve_cache_dir()` 用"是否默认 config"反推 base 目录（`app.py:66-74`），逻辑绕
- 模块级单例 `_breaker_pool` + `global`（`app.py:25, 28-33`）→ `review()` 既知 cache_dir 又知熔断持久化路径又知 vector_db 路径，耦合高
- 私有方法直调 `pool._save()`（`app.py:269`）、`getattr(static_report, 'source_file', '')` 兜底（`app.py:278`）

代码质量与其"评审代码"的定位形成讽刺。本轮通过中等重构清理，为第 9 轮静态深度迭代扫清管线。

## 2. 排除项与 YAGNI

- **不简化 `resolve_cache_dir` 的反推逻辑**：保守路线，逐字移植、零行为变化。原"is_default 反推 base"分支原样保留（含 `cfg.resolve() == default_cfg` 判断）。
- **不清理 `pool._save()` 私有直调与 `getattr(...)` 兜底**：逐字移植，留待后续迭代。
- **不引入任何新 `try/except`**：失败模式按旧实现逐字透传。
- **不为 `review()` 7 个私有方法单独写单测**：会绑死内部实现、阻碍后续清理。公共 `review()` + 现有套件已覆盖。
- **不引入 `pytest --cov` 门槛、不引入 pytest markers、不重构 `tests/` 目录**。
- **不动 `conftest.py`**。
- **不修原始测试 bug**（本轮约束）。

## 3. 模块边界与依赖方向

```
app.py            ← CLI、_fmt、_fmt_perf、_run_batch、_smoke、AIReport/FinalReport 数据类
  │
  ├── reviewer.py (新)   ← Reviewer 服务：持有 config/cache_dir/pool/vector_db_path，编排 review() 7 步
  │     │
  │     ├── config.py (新)   ← load_config / default_config_path / resolve_cache_dir / model_ver
  │     │     └── 仅依赖 stdlib，不 import 任何内部模块
  │     │
  │     └── 现有不动：cqrs_router / circuit_breaker / bulkhead / fallback_chain /
  │                   static_check / state_machine / trend_analyzer / vector_store
  │
  └── （向后兼容）app.review(...) → 委托进程级 Reviewer 单例
```

依赖单向：`app → reviewer → config → (stdlib)`。`reviewer` 不 import `app`。`config` 不 import 任何内部模块。

### 3.1 向后兼容契约（必须维持）

- 模块级函数 `app.review(code, lang, framework="", config_path="", use_cache=True) -> (FinalReport, dict)`
- `app.merge(static_report, ai_report) -> FinalReport`
- CLI `main()` 入口签名
- `AIReport` / `FinalReport` 字段集合与顺序
- `_run_batch` 内 `bh.submit(review, ...)` 调用形态不变（`review` 仍是模块级可调用对象）

`app.review` 与 `app.merge` 退化为薄转发到进程级 `Reviewer` 单例。所有现有 156 个测试调用点字节不变。

## 4. `config.py` — 逐字移植（§2）

无状态纯函数模块，仅依赖 stdlib。内容为 `app.py:58-78` 四个函数**整段移植**：

| 旧（`app.py`） | 新（`config.py`） | 移植方式 |
|---|---|---|
| `_load_config(path)` (`:58-59`) | `load_config(path)` | 逐字，去前导下划线 |
| `_default_config_path()` (`:62-63`) | `default_config_path()` | 逐字。`Path(__file__).resolve().parents[1]` 因 `config.py` 与 `app.py` 同在 `skill/scripts/`，仍指向 `skill/` |
| `_resolve_cache_dir(cache_dir, config_path)` (`:66-74`) | `resolve_cache_dir(cache_dir, config_path)` | **逐字保留** 三步中间变量 `p` / `cfg` / `default_cfg` / `is_default` / `base`，含 `is_default` 反推分支原样 |
| `_model_ver(models)` (`:77-78`) | `model_ver(models)` | 逐字：`json.dumps(models, sort_keys=True)[:32]` |

**移植纪律**：复制中间步骤，不重写等效逻辑。重写即使输出看起来相同，也可能在符号链接、大小写、相对路径解析顺序上漂移；逐字复制保证行为字节级一致。

`app.py` 删除上述 4 个 `_` 私有函数，改为 `from config import load_config, default_config_path, resolve_cache_dir, model_ver`，调用点仅改名（`_load_config` → `load_config` 等）。

## 5. `reviewer.py` — `Reviewer` 服务与 `review()` 拆分（§3）

### 5.1 构造

```python
class Reviewer:
    def __init__(self, config_path: str = ""):
        cfg_path = config_path or default_config_path()
        self.config = load_config(cfg_path)
        cache_cfg = self.config.get("cache", {})
        cache_dir_raw = cache_cfg.get("dir", "data/.cache")
        self.cache_dir = resolve_cache_dir(cache_dir_raw, cfg_path)
        self.cache_ttl_days = cache_cfg.get("ttl_days", 7)
        self.model_ver = model_ver(self.config.get("models", []))
        self.breaker_pool = create_pool(
            self.config,
            str(Path(self.cache_dir) / ".breaker_state.json"),
        )
        self.vector_db_path = str(Path(self.cache_dir) / "patterns.db")
```

构造一次，`cache_dir` / `breaker persist path` / `vector_db_path` 一次性算好为实例属性。`review()` 内部不再各自拼接路径。

### 5.2 `review()` 拆分为 7 个私有方法

```
_read_cache(key)                       → (FinalReport|None, perf_delta_ms)
_get_breaker(lang)                    → (breaker, breaker_state)
_run_static(code, lang, review_cfg)   → StaticReport
_vector_match(static_report, code)    → (vector_matches:int, vector_top_match:dict|None)
_run_ai(breaker, static_report, code, lang, framework, prompt)
                                      → (AIReport|None, ai_tier:str, new_breaker_state:str)
_merge_and_store(...)                 → FinalReport + 写缓存 + 写向量库
_done_perf(t_total)                   → 收尾 perf dict
```

`review()` 主体目标 ~60 行：构造 perf → `_read_cache` → `_get_breaker` → `_run_static` → `_vector_match` → 状态机循环调 `_run_ai` / `_merge_and_store` → `_done_perf` → return。

### 5.3 逐字移植纪律

`review()` 体内的每段实现（CQRS 读、breaker 取、static 调用、vector 遍历、状态机循环、merge、`vstore.add_from_report`、`router.write`、`pool._save`、`vstore.close`、perf 收尾）原样搬到对应私有方法。**不改逻辑、不调换顺序、不动变量名风格**。`getattr(static_report, 'source_file', '')` 兜底与 `pool._save()` 私有直调照搬（本轮不清理）。

### 5.4 单例与向后兼容

- `reviewer.py` 维护进程级 `_default: Reviewer | None` 与 `_get_default(config_path="") -> Reviewer`。仅当 `config_path` 非空且与默认实例 config_path 不同时新建实例——多数 CLI 调用传空，复用单例，等价于原 `_breaker_pool` 单例语义（进程内跨 `review()` 持久）。
- `app.py` 保留：
  ```python
  def review(code, lang, framework="", config_path="", use_cache=True):
      return _get_default(config_path).review(code, lang, framework, use_cache)
  ```
- `app.merge` 转发到 `_get_default().merge`，保留原符号。
- `_build_prompt` / `_parse_ai` / `_risk` / `merge` 整段移植到 `reviewer.py` 作为 `Reviewer` 的实例方法（`self.merge`、`self._build_prompt` 等），与 `review()` 共享 `self.config` 等实例状态。`app.py` 通过 `_get_default().merge` / `_get_default()._build_prompt` 等转发维持原符号（仅 `app.merge` 是公开符号，需保留；其余 `_` 私有符号若被外部测试直接引用会在重构期间由 grep 发现，按需转发，否则不主动暴露）。

## 6. 错误处理与数据流（§4）

### 6.1 数据流

```
Reviewer.__init__ (一次)
  config ──┬─→ cache_dir / vector_db_path / breaker persist path
           ├─→ model_ver
           └─→ breaker_pool (create_pool)

review(code, lang, ...)
  perf = {0/False 初值}  ──→ 全程同一只 dict，各步往里写
  ├─ [use_cache] key = make_key(code,lang,model_ver)
  │   cached = _read_cache(key); if cached → 收尾 return
  ├─ breaker = self.breaker_pool.get(lang)
  ├─ static_report = _run_static(...)
  ├─ (vm, vtm) = _vector_match(...)
  ├─ 状态机循环:
  │   AI_GATE: event = "allowed" if breaker.allow() else "blocked"
  │   run_ai:  ai_report, ai_tier, _ = _run_ai(...); self.breaker_pool._save()  # 逐字保留
  │   merge_*: report = self.merge(static_report, ai_report)
  │            if router: router.write(key, report.__dict__, lang, code_lines)
  │            if not cache_hit: vstore.add_from_report(...)  # 逐字保留
  │            vstore.close(); return report, perf
  └─ (终态) return merge(static_report, None), perf   # 逐字保留兜底
```

### 6.2 错误处理策略——逐字移植，不改语义

| 位置 | 旧行为 | 新行为 |
|---|---|---|
| `load_config` 文件不存在 | `Path.read_text` 抛 `FileNotFoundError` 冒泡到 CLI | **保留**——`Reviewer.__init__` 不加 try |
| CQRS `router.try_read` 异常 | 不显式 catch，依赖 `CQRSRouter` 内部吞 | **保留** |
| `VectorStore` 打开/搜索失败 | 不显式 catch | **保留** |
| `_run_ai` FallbackChain 失败 | `chain.call` 内部降级返回 tier | **保留** |
| `add_from_report` 失败 | 不显式 catch | **保留** |

**本轮不引入任何新 `try/except`**。

### 6.3 资源关闭顺序（逐字保留）

- `vstore.close()` 在 merge 后调（`app.py:282-283`）
- 终态 fallback 分支也调 `vstore.close()`（`app.py:288-289`）
- `router` 无 close（CQRSRouter 旧代码无显式关闭，保留）
- `breaker_pool` 无 close（进程级，保留）

## 7. 测试策略（§5）

### 7.1 核心约束

- 现有 156 测试 100% 绿、仓储不动、不修原始测试 bug。
- 重构开始前必跑 `cd tests && pytest -q` 记录基线（156 passed），作为回归对比基准。

### 7.2 Oracle 陷阱与修正（B 路径）

**陷阱**：原方案"用旧 `app._resolve_cache_dir` 作 oracle"不可行——§2 删除该函数后 `app._resolve_cache_dir` 不存在，测试中调它会 `AttributeError`。

**修正（B 路径：重构前固化快照）**：

1. **重构前 commit**（独立前置 commit）：
   - 新增临时脚本 `tests/_snapshot_legacy.py`，调用**当时仍存在的** `app._resolve_cache_dir`，对一组固定输入（覆盖：绝对路径 / 相对路径 / 空 cache_dir / 空 config_path / 默认 config / 自定义 config）运行，输出落盘到 `tests/fixtures/config_cache_dir.json`。
   - 提交脚本 + 快照文件。
   - **随后删除临时脚本**（一次性使命完成，不留仓库）。
2. **§2 重构 commit**：移 `_resolve_cache_dir` 到 `config.py`，删 `app.py` 旧函数。
3. **`test_config.py`**：`@pytest.mark.parametrize` 遍历 `tests/fixtures/config_cache_dir.json`，对新 `config.resolve_cache_dir` 断言输出 == 快照记录值。

快照来源是被检对象（旧实现）的程序运行产出，不是手抄转写，自证循环被切断；快照文件独立于实现存在，重构期间始终可达。

### 7.3 新增测试（最小集）

| 文件 | 测试类 | 目的 | 形态 |
|---|---|---|---|
| `tests/test_config.py`（新） | `TestConfigPureFunctions` | `resolve_cache_dir`/`model_ver`/`load_config`/`default_config_path` 逐字移植等价 | oracle = `fixtures/config_cache_dir.json`，纯函数 |
| `tests/test_reviewer.py`（新） | `TestReviewerConstruction` | `Reviewer()` 默认构造不抛、`cache_dir` 解析正确、`breaker_pool` 非空、`model_ver` 对应 config | 仅测构造 |
| 同上 | `TestReviewForwardingParity` | `Reviewer.review()` 与 `app.review()` 相同输入/mock 下 `FinalReport.risk` 一致、`len(findings)` 一致 | 复用 `conftest` 已有 buggy/clean fixtures + mock HTTP，不打补丁 |

新增测试守则：
1. 不动 `conftest.py`。
2. 不 mock `Reviewer` 私有方法（黑盒，只走公共 `review()`）。
3. `TestReviewForwardingParity` 用 `mock_http_success` 走完一次 T1，比 `app.review` 与 `Reviewer.review` 同 seed 产出的 `risk`——唯一目的是防 §3 转发链路退化。
4. 不引入 pytest markers。

### 7.4 回归判据（合并前必达）

- [ ] 原 156 测试全绿（0 fail / 0 error）
- [ ] `tests/test_config.py` + `tests/test_reviewer.py` 新增全绿
- [ ] `python skill/scripts/app.py --smoke` 跑通
- [ ] `python -m pytest tests/ -q` 总数 = 156 + 新增数，无 regression

## 8. 提交计划（implementation plan 待 writing-plans 细化）

1. **chore: 固化 resolve_cache_dir 行为快照** — 新增临时脚本 + `tests/fixtures/config_cache_dir.json`，跑后删脚本。
2. **refactor: 提取 config.py（逐字移植）** — §2，删 `app.py` 4 个私有函数，改 import 与调用点改名。
3. **refactor: 引入 Reviewer 服务，拆分 review()** — §3/§4，新增 `reviewer.py`，`app.review`/`app.merge` 转发。
4. **test: 新增 config 与 reviewer 单测** — §7.3。
5. **docs: iteration_log 补第 8 轮记录** — 5 步法（痛点→量化→根因→方案→度量）。

每步后跑 `pytest -q`，绿数下降即回到上一绿状态。

## 9. 下一轮预告（不在本轮）

- 第 9 轮：Java/Go/JS 静态分析深度提升（AST 或更准语义模式），修 Java `hardcoded_secret` 误报。本轮清理后的 `Reviewer` 管线为其扫清障碍。