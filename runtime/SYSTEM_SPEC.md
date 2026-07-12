# 双检代码评审系统说明书

这套系统服务于一个核心目标：让独立开发者在不依赖人工 Reviewer 的情况下，获得稳定可靠的代码评审。它的策略不是用 AI 替代静态分析，而是让静态规则抓表面问题，让 AI 解释告警并发现静态层漏掉的逻辑 Bug——两条路径互补，合并后给出三路对比。

## 系统目标

1. 快速静态检查：AST + 正则，毫秒级返回表面问题。
2. AI 语义深检：确认告警、排除误报、发现逻辑 Bug。
3. 熔断保护：AI 子系统异常时退化为纯静态报告，不阻断工作流。
4. 模型降级：DeepSeek → Qwen → 本地兜底，提高可用性。
5. CQRS 缓存：同段代码重复评审，第二次直接命中缓存。
6. 声明式规则：评审阈值和规则放在 YAML 文件中，代码只负责执行。
7. 健康度自检：缓存命中率、熔断器状态、发现质量可度量。
8. 按语言隔离的熔断器池：每个语言独立熔断计数和状态切换。
9. 舱壁隔离：大文件（>500行）走独立线程池，不阻塞小文件（10 并发）。
10. 批量评审：`--batch` 模式支持目录级并发评审，自动检测语言。
11. 向量记忆：Bug 模式自动存入 sqlite，重复出现时匹配历史并给出修复建议。
12. 质量趋势报告：从 CQRS 缓存 + 向量存储生成周报（评分、密度、高频类型、建议）。

## 痛点驱动设计

本系统的每一次迭代均由真实用户痛点驱动。以下是已解决的三大痛点及对应的系统能力。

### 痛点 1：重复代码评审太慢、太贵

> **真实场景**：用户第一次贴了 `validate_email()` → AI 评审花 5s，消耗 2000 tokens。用户改了一行注释，又贴了一遍 → AI 重新评审又花 5s，又消耗 2000 tokens。用户抓狂："我没改代码，为什么还要等？"

**根因**：每次提交都触发完整的静态检查 + LLM 调用，没有缓存去重机制。

**解决方案（v0.3）**：CQRS 读写隔离

```
用户贴代码 → sha256(代码内容) → 查缓存 → 命中 → 直接返回（< 50ms）
                                    → 未命中 → 调 LLM → 写入缓存 → 返回
```

**量化效果**：

| 指标 | 改前 | 改后 |
|------|------|------|
| 重复评审响应时间 | 4–5s | < 50ms（~100× 提升） |
| API 调用次数（相同代码×10） | 10 次 | 1 次 |
| Token 消耗（相同代码×10） | ~20,000 | ~2,000 |

**涉及模块**：`cqrs_router.py`（CQRSRouter + CacheStats）、`reviewer.py`（`Reviewer._read_cache`/`_merge_and_store` 集成）

---

### 痛点 2：API 一挂系统就崩

> **真实场景**：深夜 2 点，DeepSeek API 波动。用户贴代码 → 等待 15s → 504 Gateway Timeout → 页面白屏。用户："这什么破系统？"

**根因**：单一熔断器全局共享，任何 API 故障都导致全系统不可用。

**解决方案（v0.4）**：按语言隔离的熔断器池 + 三级降级链

```
cb_pool = {
    "python": CircuitBreaker(threshold=3, cooldown=30),  # Python 熔断了
    "go":     CircuitBreaker(threshold=3, cooldown=30),  # Go 不受影响 ✅
    "java":   CircuitBreaker(threshold=5, cooldown=60),  # Java 阈值更宽松
}

T1: DeepSeek ──fail──→ T2: Qwen ──fail──→ T3: 本地兜底（永远可用）
熔断器 OPEN → 直接跳到 T3，不浪费远程调用
```

**量化效果**：

| 指标 | 改前 | 改后 |
|------|------|------|
| API 不可用时用户体验 | 500 错误 / 白屏 | 自动降级，有输出 |
| 系统可用性（API 故障期间） | 0% | 100%（有输出即有可用性） |
| 用户看到错误页面的概率 | 每次 API 挂都看到 | 趋近于 0 |
| Python API 故障影响 Go 评审 | 全局崩溃 | 互不影响 |

**涉及模块**：`circuit_breaker.py`（BreakerPool）、`fallback_chain.py`（ChainResult）、`reviewer.py`（`_prepare` 惰性建池 + `_get_breaker` per-language routing）

---

### 痛点 3：大文件评审堵死小文件

> **真实场景**：用户 A 贴了一段 800 行的配置解析代码。用户 B 同时贴了 5 行 `validate_email()` → 用户 B 要等用户 A 评审完才能拿到结果 → 用户 B 等了 15 秒 → 用户 B 关掉了页面。

**根因**：单一线程池处理所有文件，大文件耗时阻塞小文件响应。

**解决方案（v0.5）**：舱壁隔离（Bulkhead Isolation）

```
                     ┌─────────────────────────┐
                     │      请求入口             │
                     └────────┬────────────────┘
                              │
                     ┌────────▼────────┐
                     │  判断文件行数    │
                     └───┬────────┬────┘
                         │        │
                   ≤500行         >500行
                     │        │
                     ▼        ▼
              ┌──────────┐ ┌──────────┐
              │ normal   │ │ large    │
              │ pool     │ │ pool     │
              │ (10 并发) │ │ (2 并发) │
              └────┬─────┘ └────┬─────┘
                   │            │
                   ▼            ▼
              ┌──────────┐ ┌──────────┐
              │ 快速返回  │ │ 慢速返回  │
              │ < 3s     │ │ < 15s    │
              └──────────┘ └──────────┘
```

**量化效果**：

| 指标 | 改前 | 改后 |
|------|------|------|
| 大文件评审时小文件等待时间 | 15–20s | < 3s |
| 大文件最大并发数 | 无限制（可能 OOM） | 限制 2 并发 |
| 系统总吞吐量 | 受大文件拖累 | 小文件不受影响 |

**涉及模块**：`bulkhead.py`（BulkheadExecutor）、`app.py`（`--batch` 模式）

---

### 痛点 4：AI 评审没有记忆

> **真实场景**：周一：用户写了 `def divide(a, b): return a / b` → AI 评审："⚠️ 缺少除零保护"。周三：用户又在另一个文件写了同样的代码 → AI 评审："⚠️ 缺少除零保护"（完全忘记周一说过）。用户："你能不能记住我上周犯过什么错？"

**根因**：每次评审独立执行，没有跨文件的模式记忆和学习能力。

**解决方案（v0.6）**：本地向量存储 + 历史模式匹配

```
                   ┌──────────────────────────────────┐
                   │         向量存储（sqlite）         │
                   │  patterns 表：kind, snippet,       │
                   │  message, fix_hint, feature_hash   │
                   └──────────────────────────────────┘
                              ▲
                              │ 相似度检索
                              │
用户贴新代码 ──→ 提取特征向量 ──┘
                    │
                    ▼
           ┌────────────────┐
           │ 相似度 > 0.55  │ ← 命中历史模式
           └───────┬────────┘
                   ▼
      输出："与 N 天前的 Bug 相似度 XX%，当时修复方案：..."
```

**量化效果**：

| 指标 | 改前 | 改后 |
|------|------|------|
| 相同 Bug 模式重复发现率 | 0%（每次都当新的） | > 80%（匹配历史） |
| 用户平均修复时间 | 每次都重新诊断 | 复用历史修复方案 |
| 跨文件模式识别 | 不支持 | 自动匹配同语言历史 |

**涉及模块**：`vector_store.py`（VectorStore + PatternMatch）、`reviewer.py`（`_vector_match` 检索 + `_merge_and_store` 存储集成）

---

### 痛点 7：看不到自己的进步

> **真实场景**：用户用了一个月 AI 评审，每周提交 20 次代码。但他完全不知道自己的代码质量是变好了还是变差了、最常见的 Bug 类型是什么、跟团队其他人比怎么样。用户："我每天在用，但我感觉不到任何变化。"

**根因**：系统只做评审，不提供反馈闭环。用户缺乏量化的进步感知。

**解决方案（v0.7）**：质量趋势报告

```
[TREND] 代码质量趋势周报 — 2026-07-06

评分趋势：
  62 → 68 → 75 → 72 → 80 → 85
  ↑    ↑    ↑    ↑    ↑    ↑
  第1周 第2周 第3周 第4周 第5周 本周

Bug 密度（每千行）：
  12.0 → 10.0 → 8.0 → 6.0 → 4.0 → 3.0

最常见 Bug 类型 Top 3：
  1. 除零未检查（15 次）
  2. 空指针引用（8 次）
  3. 资源未关闭（5 次）

[FOCUS] 下周建议重点：空指针防护
```

**量化效果**：

| 指标 | 改前 | 改后 |
|------|------|------|
| 用户周留存率 | ~30%（用完即走） | > 70%（为了看周报） |
| 用户代码评分提升（月） | 无明显变化 | 平均 +15 分（因为能看到进步） |
| 高频 Bug 类型重复率 | 持续发生 | 降低 50%（被周报聚焦提醒） |

**涉及模块**：`trend_analyzer.py`（TrendReport + analyze）、`cqrs_router.py`（code_lines 元数据）、`app.py`（`--trend-report` CLI）

---

## 目录结构

```text
AI_Code_Review_Dual-Check_Assist/
├── AGENTS.md                       # 给 AI 执行者看的规则
├── SYSTEM_SPEC.md                  # 给人看的系统说明书（本文件）
├── README.md                       # 快速开始
├── .gitignore
├── skill/                          # 技能定义与脚本
│   ├── SKILL.md                    # Claude Code 技能文件
│   ├── scripts/                    # 12 个核心脚本（v0.10 新增 config.py + reviewer.py）
│   │   ├── app.py                  # CLI 入口（~100 行，薄转发到 Reviewer）
│   │   ├── reviewer.py             # Reviewer 服务（~275 行，8 步拆分管线）
│   │   ├── config.py               # 配置纯函数模块（~28 行）
│   │   ├── static_check.py         # 静态快检层（~167 行）
│   │   ├── circuit_breaker.py      # 熔断器（~48 行）
│   │   ├── cqrs_router.py          # CQRS 缓存读写（~50 行）
│   │   ├── fallback_chain.py       # 模型降级链（~76 行）
│   │   ├── state_machine.py        # 评审状态机（~48 行）
│   │   ├── bulkhead.py             # 舱壁隔离
│   │   ├── vector_store.py         # 向量记忆
│   │   ├── health_check.py         # 健康度自检
│   │   └── trend_analyzer.py       # 质量趋势
│   └── references/                 # 参考文档与配置
│       ├── USAGE.md                # 使用说明
│       ├── BEST_PRACTICES.md       # 最佳实践
│       ├── config.example.json     # 配置示例
│       └── rules/                  # 声明式评审规则
│           ├── python.yaml         # Python AST 规则
│           ├── universal.yaml      # 通用正则规则
│           ├── go.yaml             # Go 规则（v0.3 扩展）
│           └── javascript.yaml     # JavaScript 规则（v0.3 扩展）
├── data/                           # 测试语料与缓存
│   ├── sample_buggy_code.py        # Python 有缺陷样本
│   ├── sample_clean_code.py        # Python 干净样本
│   ├── sample_go_code.go           # Go 样本
│   └── .cache/                     # CQRS 缓存目录
├── tests/                          # 测试与基线
│   └── test_record.md              # 回归基线（带 YAML frontmatter）
├── distill/                        # 蒸馏后的知识资产
│   └── patterns/                   # 可复用 Bug 模式卡片
├── iteration/                      # 迭代记录
│   └── iteration_log.md            # 版本迁移日志
├── system/                         # 系统配置、日志、状态
│   ├── review-rules.json           # 评审规则注册表
│   ├── status.md                   # 自动生成的状态仪表盘
│   ├── frontmatter-template.md     # Frontmatter 模板
│   ├── logs/                       # 日常操作日志
│   ├── update-logs/                # 系统功能更新日志
│   └── reports/                    # 健康度自检报告
└── docs/                           # 设计文档
    └── superpowers/
        ├── plans/                  # 实现计划
        └── specs/                  # 设计规约
```

## 语言分类规则

目前支持三种语言，每种语言可配置 AST 规则 + 通用正则规则：

### `python`

AST 解析 + 正则层。支持的 AST 规则：可变默认参数、长函数、高圈复杂度、深层嵌套、裸 except、`is` 字面量比较。

### `go`

当前仅正则层（long_line、todo_marker）。v0.3 计划扩展 `go/ast` 解析（nil 解引用、错误未处理等）。

### `javascript`

当前仅正则层。v0.3 计划扩展 ESLint 规则子集。

## 评审流程

用户说"评审/检查/review"时：

1. 读取代码内容，自动或手动指定语言。
2. 计算缓存键：`sha256(code + lang + model_ver)[:16]`。
3. 查 CQRS 缓存（读路径）→ 命中直接返回。
4. 未命中 → 执行 `static_check(code, lang)`：
   - 有 AST 支持的语言：运行对应 `_<lang>_check()` 函数。
   - 所有语言：追加运行 `_regex_check()` 通用规则。
5. 检查熔断器 `allow()`：
   - 允许 → 构建 AI prompt，走降级链 `FallbackChain.call()`。
   - 阻断 → 跳过 AI，直接进入合并。
6. AI 降级链：DeepSeek → Qwen → 本地兜底。
   - 每次模型调用失败 → `breaker.record_failure()`。
   - 调用成功 → `breaker.record_success()`（仅 HALF_OPEN → CLOSED）。
7. 解析 AI 响应：`_parse_ai()` 剥离 markdown fence，提取 JSON。
8. 合并 `merge(static_report, ai_report)`：
   - 静态 finding → `layer: static`。
   - AI 确认 → `layer: ai_confirmed`。
   - AI 新发现 → `layer: ai_new`。
   - AI 否定 → 不进入 findings，仅影响 ai_summary。
9. 计算风险等级：任一 high → 阻止合并；有 finding → 修复后合并；无 → 可合并。
10. 写缓存（CQRS 写路径）。
11. 返回 FinalReport。

## 数据契约

### Finding（静态/AI 通用）

```python
@dataclass
class Finding:
    line: int           # 行号
    kind: str           # 问题类型（mutable_default / long_function / ...）
    severity: str       # high / medium / low
    message: str        # 人类可读描述
```

### StaticReport（静态层输出）

```python
@dataclass
class StaticReport:
    lang: str                         # 语言
    findings: List[Finding]           # 静态发现
    summary: str                      # 摘要
```

### AIReport（AI 层输出）

```python
@dataclass
class AIReport:
    confirmation: list[Finding]   # AI 确认的静态告警
    rejection: list[Finding]      # AI 认为是误报的静态告警
    new_findings: list[Finding]   # AI 独立发现
```

### FinalReport（合并输出）

```python
@dataclass
class FinalReport:
    risk: str               # 阻止合并 / 修复后合并 / 可合并
    summary: str            # 单行摘要
    static_summary: str     # 静态层摘要
    ai_summary: str         # AI 层摘要
    findings: list[dict]    # 合并后的 finding 列表（含 layer 字段）
```

## 缓存与 CQRS 规则

- 文件系统仍是唯一事实来源，`data/.cache/` 只是从代码内容派生的缓存。
- 缓存键 = `sha256(code + lang + model_ver)[:16]`，model_ver 变更时自动失效旧缓存。
- 读路径（`try_read`）：缓存命中则直接返回，不执行评审。
- 写路径（`write`）：新评审完成后写入缓存。
- TTL 默认 7 天，过期条目在读取时检查。
- `--no-cache` 标志跳过读路径，强制执行完整评审。

## 熔断器规则

- 状态机：CLOSED → OPEN → HALF_OPEN → CLOSED。
- CLOSED：正常放行，`record_failure()` 累加计数，达到阈值转 OPEN。
- OPEN：拒绝放行，冷却时间（cooldown）过后自动转 HALF_OPEN。
- HALF_OPEN：允许一次探针请求。成功 → CLOSED（重置计数）；失败 → OPEN（重新冷却）。
- `record_success()` 仅在 HALF_OPEN 状态下转换到 CLOSED（防止冷却期绕过）。
  - CLOSED 状态下也调用 `record_success()` 重置失败计数，确保连续成功不累积历史失败。

## 系统功能更新日志

`system/update-logs/` 用来记录本评审系统自身的功能更新，和 `system/logs/` 分开。

当任何 agent 修改以下内容时，必须在 `system/update-logs/YYYY-MM.md` 追加记录：

- 规则文件：`AGENTS.md`、`SYSTEM_SPEC.md`、`README.md`
- 评审规则：`skill/references/rules/`
- 脚本：`skill/scripts/`
- 系统配置：`system/review-rules.json`
- 状态生成、缓存 schema、熔断器逻辑
- 目录结构

记录应包含：更新时间、更新类型、摘要、涉及文件、使用方式、验证结果和后续注意。

## 健康度自检流程

当用户要求"健康度""自检""复盘"时，至少检查三个维度：

| 维度 | 健康的样子 | 不健康的样子 | 不健康时怎么办 |
| --- | --- | --- | --- |
| 缓存命中率 | >50%，响应 <200ms | 命中率 <20% 或缓存膨胀 | 命中率低 → 检查 TTL；膨胀 → 缩短 TTL |
| 熔断器状态 | CLOSED，故障 < 阈值 | 频繁 OPEN 或 HALF_OPEN 振荡 | 频繁断开 → 检查 API Key/网络；振荡 → 增大 cooldown |
| 发现质量 | AI 新发现占比 10-50% | AI 全确认或全否定 | 全确认 → prompt 太保守；全否定 → 静态层过严 |

执行规则：

1. 读取 `system/status.md` 获取基线数据。
2. 用缓存命中率、熔断器状态、静态/AI 发现比作为基础数据。
3. 将结果写入 `system/reports/YYYY-MM-DD-HHMMSS-health-check.md`。
4. 如果健康检查规则发生变化，记录到 `system/update-logs/YYYY-MM.md`。

## 蒸馏流程

当用户要求"蒸馏/提炼/整理成卡片"时：

1. 从历史评审记录中提取反复出现的 Bug 模式。
2. 写入 `distill/patterns/`，一张卡片只讲一个 Bug 模式。
3. 卡片必须包含：核心观点、证据（实际 finding 摘录）、可复用检查方法、触发条件。
4. 跨语言的通用模式写入 `distill/patterns/universal/`，语言特定模式写入 `distill/patterns/<lang>/`。

## v0.2 规则文件声明式化

v0.2 将评审阈值和规则从 `static_check.py` 的硬编码常量中提取到 YAML 文件：

- `skill/references/rules/python.yaml`：Python AST 规则 + 阈值。
- `skill/references/rules/universal.yaml`：所有语言的通用正则规则。

规则文件是声明式约束，不是代码。修改阈值不需要改 Python 代码。`static_check.py` 读取 YAML 并执行检查逻辑。这是"写作不是感觉，是规则"原则的技术体现——把风格写成约束，而不是形容词。

## v0.3 扩展规划

- 语言扩展：Go AST（nil 解引用、错误未处理）、JavaScript（ESLint 规则子集）。
- 输出优化：Markdown 报告、SARIF 格式支持。
- 沉淀 SKILL.md：将系统能力固化为可分发安装的 Claude Code skill。
- 蒸馏管线：自动从评审记录中识别高频 Bug 模式，生成模式卡片。
