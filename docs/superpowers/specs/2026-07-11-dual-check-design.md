---
date: 2026-07-11
topic: AI 代码评审「双检」助手系统设计
status: approved
---

# AI 代码评审「双检」助手 — 设计规约

## 1. 项目定位

一个 AI 代码评审「双检」助手系统。AI 是代码质量分析师——读代码 → 理解上下文 → 检测 Bug + 风格问题 + 优化建议 → 告诉用户哪里有问题、怎么改、该不该合并。

**MVP 核心功能**：粘贴代码段 + 语言/框架上下文 → AI 分析代码质量（Bug 检测 + 风格评分 + 可读性评估）→ 用 CQRS 读写隔离加速重复评审 → 给出优化建议和风险等级。

**「双检」定义**（已确认）：静态规则快检 + AI 语义深检。静态层抓表面问题（命名、复杂度、明显反模式），AI 层做两件事——解释静态层的告警，并发现静态层漏掉的逻辑 Bug。两者对照合并成一份报告。

**核心痛点**：自己写的代码有没有 Bug 心里没底；不好意思总麻烦同事做 Code Review；CI 通过了但上线还是出问题；同样的代码错误反复犯；看不懂别人代码的质量。

**适用人群**：独立开发者、小团队无专职 Reviewer 的开发者、想提升代码质量但缺乏反馈的编程学习者、面试时想展示工程能力的技术人。

**硬约束**：
- 免费大模型 API（DeepSeek / Qwen）
- Python 标准库，无第三方依赖
- 每个核心脚本文件 < 120 行（硬约束）。六个文件合计约 400-500 行，每个文件单一职责

**最终形态**：三轮迭代后沉淀为可复用技能文件（SKILL.md + 配套 scripts/references）。

## 2. 双检核心架构

### 2.1 数据流（单次评审）

```
[粘贴代码 + 语言/框架]
        │
        ▼
   state_machine 驱动: init → static → ai_gate → ai_run → merge → done
        │
        ▼
   cqrs_router 读路径: 查缓存 (key = sha256(code+lang+model_ver)[:16])
        # model_ver = 配置中 models 列表的版本戳（如模型名+顺序的哈希），
        # 换模型链配置后旧缓存自动失效
        ├─命中 → 直接返回 cached report（不碰 AI）
        └─未命中 ↓

   static_check (ast/正则，纯标准库)
   检查: 复杂度估算 / 块嵌套深度 / 超长函数 / 命名规范 / TODO/FIXME / 空 catch
        │
        ▼
   circuit_breaker 检查 (AI 入口闸门)
        ├─OPEN     → 跳过整段 AI，merge 阶段只合并静态结果 + 标记"降级模式"
        ├─HALF_OPEN→ 放行一次试探调用 ↓
        └─CLOSED   → 放行 ↓

   fallback_chain (仅在闸门放行时跑)
        DeepSeek 失败 → Qwen 失败 → 本地兜底（基于静态结果的最小说明，非空 stub）
        每次失败 → record_failure() 喂给 circuit_breaker
        每次成功 → record_success()
        连续失败超阈 → circuit_breaker 转 OPEN

   ai_deep_check: 拿静态结果 + 原码 →
        ├ 解释静态告警（为何是问题）
        └ 发现静态层漏掉的逻辑 Bug

   merge: 合并两路 → 三类对照 → 风险等级 + 优化建议 + 是否可合并
        ├ 静态命中、AI 确认（高可信）
        ├ 静态命中、AI 否定（可能是误报）
        └ AI 独有发现（静态漏掉的逻辑 Bug，最有价值）
        若 AI 缺席（熔断降级）→ 报告标注"仅静态，AI 不可用，建议稍后重试"

   cqrs 写路径: 落盘 JSON 到 data/.cache/<hash>.json
        │
        ▼
   输出报告
```

### 2.2 熔断器与 Fallback 的关系（已修正）

**逻辑约束**：circuit_breaker 是 AI 子系统的健康闸门，语义是「整个 AI 子系统不健康就别试」；fallback_chain 仅解决「主模型不可用换备用」。两者关系：**闸门在前，链在后**；链的失败喂给闸门，闸门 OPEN 后链根本不跑。

降级路径语义：熔断时不是报错，而是退化成"仅静态报告"，体感是结果变薄而非系统挂掉。

### 2.3 关键接口契约

```
static_check(code, lang) -> StaticReport
ai_deep_check(static_report, code, lang) -> AIReport | None   # None = 熔断降级
merge(static_report, ai_report | None) -> FinalReport
```

`AIReport` 允许为 `None`（熔断降级时），`merge` 在此情况下输出"仅静态"报告。任一环节缺席都不破坏输出结构——**契约一致性优先于功能完整**。

## 3. 六个脚本文件职责与接口

每个文件 < 120 行，单一职责。

### 3.1 `app.py`（~90 行）— CLI 入口与编排
- 解析命令行：`code`（文件路径或 `--code` 内联）、`--lang`、`--framework`、`--no-cache`、`--json`
- 读取配置 `config.yaml`（模型链、阈值、缓存路径）
- 按顺序调用：`cqrs_router.try_read` → `state_machine` 驱动流程 → `cqrs_router.write`
- 格式化输出：人读版（终端彩色分段）或 `--json` 版（结构化报告）
- 配置加载、CLI 解析、流程编排，不含业务逻辑

### 3.2 `circuit_breaker.py`（~60 行）— AI 子系统闸门
```python
class CircuitBreaker:
    state: CLOSED | OPEN | HALF_OPEN
    failures: int
    threshold: int      # 连续失败多少次转 OPEN（配置，默认 3）
    cooldown: float     # OPEN 多久后转 HALF_OPEN（配置，默认 60s）
    opened_at: float

    def allow() -> bool          # 调用前问闸门
    def record_success()         # 成功重置计数，HALF_OPEN→CLOSED
    def record_failure()        # 失败累计，达阈转 OPEN
```
- 纯标准库，无外部依赖
- HALF_OPEN 放行一次试探，成功转 CLOSED，失败转 OPEN

### 3.3 `cqrs_router.py`（~70 行）— 读写分离
```python
def try_read(key) -> report | None          # 读路径：从 data/.cache/<hash>.json
def write(key, report)                        # 写路径：落盘 JSON
def make_key(code, lang, model_ver) -> str    # sha256(code+lang+model_ver)[:16]
```
- 命中直接返回，绝不碰 AI
- `model_ver` 进 key：换模型链配置后旧缓存自动失效，避免旧报告误导

### 3.4 `fallback_chain.py`（~80 行）— 模型降级链
```python
class FallbackChain:
    models: list[ModelConfig]    # 配置驱动，默认 [DeepSeek, Qwen]
    def call(prompt) -> str       # 依次尝试，全部失败返回本地兜底
```
- 只在 circuit_breaker 放行后才被调用
- 用 `urllib.request`（标准库）走 OpenAI 兼容格式，无第三方 HTTP 库
- **本地兜底（v0.1 即做实，非空 stub）**：基于静态结果生成最小说明报告（"未连上 AI，纯静态层结论如下…"），确保降级场景也能产出有意义的 merge 输出
- 每次失败调用 `breaker.record_failure()`，成功调用 `breaker.record_success()`

### 3.5 `state_machine.py`（~80 行）— 评审流程状态机
```python
states = [INIT, STATIC, AI_GATE, AI_RUN, MERGE, DONE]
# transitions: 静态 → 闸门 → AI运行 → 合并 → 完成
#              闸门拒绝 → 直接合并（降级） → 完成

def next(state, event) -> (new_state, action)
```
- 驱动 `app.py` 的主循环步进
- 降级路径（闸门拒绝）与正常路径都走同一条 merge 出口，保证输出结构一致
- 状态机驱动而非 if/else 串联：流程可视化、降级路径统一、v0.3 加增量评审只多加两状态

### 3.6 `static_check.py`（~80 行）— 静态快检层
```python
def static_check(code: str, lang: str) -> StaticReport
```
- Python 用 `ast` 模块解析：圈复杂度估算、块嵌套深度、超长函数、可变默认参数、`is` 比字面量、裸 except、未关闭资源
- 其他语言（Go/JS 等）用通用正则：行长、缩进深度、命名启发、TODO/FIXME 标记
- 纯标准库，无第三方依赖
- 输出 `StaticReport`（findings 列表，每条含行号、类型、严重度、消息），供 `ai_deep_check` 解释和 `merge` 对照

**`ai_deep_check` 的归属**：它由 `fallback_chain.py` 承载。`fallback_chain.call(prompt)` 接收由 `app.py` 构造的评审 prompt（含静态结果 + 原码 + 语言/框架上下文），经降级链返回 AI 文本；`app.py` 解析该文本为 `AIReport`。即：prompt 构造与 AI 调用降级是同一职责（都在 `fallback_chain.py`），AI 返回的文本解析在 `app.py` 编排层。这样 §2.1 数据流中的 `ai_deep_check` 步骤 = `app.py` 构造 prompt → `fallback_chain.call` → `app.py` 解析结果。

## 4. references / data / tests / iteration 结构

### 4.1 `skill/references/`

**`config.example.yaml`**（~40 行）— 整个系统唯一配置入口
```yaml
models:
  - name: deepseek
    endpoint: https://api.deepseek.com/v1/chat/completions
    api_key_env: DEEPSEEK_API_KEY   # 从环境变量读，不硬编码
    model: deepseek-chat
    timeout: 30
  - name: qwen
    endpoint: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
    api_key_env: DASHSCOPE_API_KEY
    model: qwen-plus
    timeout: 30

breaker:
  threshold: 3
  cooldown: 60

cache:
  dir: data/.cache
  ttl_days: 7

review:
  max_function_lines: 50
  max_nesting: 4
  max_file_lines: 800
```

**`USAGE.md`**（~80 行）— 给人看
- 三种调用方式：CLI 文件 / `--code` 内联 / 管道
- 「双检」是什么、为什么要两路
- 输出报告各字段含义（风险等级、三类对照、降级标注）
- 缓存命中与 `--no-cache` 强制重评
- 环境变量配置（API key 从哪设）

**`BEST_PRACTICES.md`**（~70 行）— 评审方法论沉淀
- 什么样的代码值得双检（>30 行、有逻辑分支、非模板）
- 静态层局限：抓不到的（并发、参数语义、业务逻辑）
- AI 层局限：可能误报（缺上下文），如何给框架提示降低误报
- 何时该信静态、何时该信 AI、两者冲突时怎么办
- 评审报告的三个风险等级判定标准（可合并 / 修复后合并 / 阻止合并）

### 4.2 `data/` — 测试语料（固定三份，迭代中可加）
- `sample_buggy_code.py` — 故意埋 bug：空 except、深层嵌套、未关闭文件、可变默认参数、`is` 比字面量。每个 bug 加 `# BUG:` 注释方便断言。
- `sample_clean_code.py` — 对照组：同功能但写法正确。验证不误报。
- `sample_go_code.go` — v0.3 多语言扩展用，v0.1 阶段只验证"静态层不崩、AI 层能识别语言"。

### 4.3 `tests/test_record.md` — 仿参考项目七要素格式
不写 pytest（项目要"测试记录"而非"测试代码"），而是每次迭代后追加：
```
## v0.1 验证 (2026-07-11)
- 验证对象：...
- 命令：...
- 预期：...
- 实际：...
- 结论：通过 / 失败原因
- 后续：
```
每个样本代码跑一遍 `app.py`，把实际输出贴进 `test_record.md` 作为回归基线。下次迭代改了逻辑，重跑对比是否回归。

**权衡（已接受）**：牺牲自动回归（人得手动对比），但契合项目"迭代日志驱动"的风格，且不引入测试框架复杂性。

### 4.4 `iteration/iteration_log.md` — 仿参考项目 `update-logs`
每轮追加七要素：更新类型 / 版本迁移 / 摘要 / 涉及文件 / 使用方式 / 验证结果 / 后续注意。

### 4.5 `README.md`（仓库根）
讲选题、功能、用法，指向各文件。

## 5. 仓库最终产物结构

```
ai-code-review-dual-check/
├── README.md
├── docs/
│   └── superpowers/specs/
│       └── 2026-07-11-dual-check-design.md   # 本文件
├── skill/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── app.py
│   │   ├── circuit_breaker.py
│   │   ├── cqrs_router.py
│   │   ├── fallback_chain.py
│   │   ├── state_machine.py
│   │   └── static_check.py
│   └── references/
│       ├── config.example.yaml
│       ├── USAGE.md
│       └── BEST_PRACTICES.md
├── data/
│   ├── sample_buggy_code.py
│   ├── sample_clean_code.py
│   └── sample_go_code.go
├── tests/
│   └── test_record.md
└── iteration/
    └── iteration_log.md
```

## 6. 三轮迭代路线图

仿参考项目版本号风格（v0.1 → v0.2 → v0.3），每轮一个明确能力增量，落 `iteration/iteration_log.md` 七要素。**每轮结束等用户指令再进下一轮，不自动往下跑。**

### v0.1 — 双检并行 MVP（第一个可跑版本）
**目标：核心能力一步到位，证明"双检"信息增益真实存在。**

六个脚本全落地（骨架复杂度一次性承受，避免 v0.2 重构）：
- `app.py`：CLI + 编排，跑通 main 链路
- `static_check.py`：Python `ast` + 通用正则（行长/嵌套/命名/TODO/空 catch）
- `cqrs_router.py`：hash 缓存，命中直接返回
- `fallback_chain.py`：DeepSeek → Qwen → **本地兜底（v0.1 即做实，基于静态结果生成最小说明，非空 stub）**，承载 `ai_deep_check` 的 AI 调用降级
- `circuit_breaker.py`：CLOSED/OPEN/HALF-OPEN 三态，阈值=3
- `state_machine.py`：init→static→ai_gate→ai_run→merge→done，含降级分支

产出三样本报告，贴进 `tests/test_record.md` 作回归基线。`iteration_log.md` 记第一条 v0.1。

**验证基准**：sample_buggy 的 5 个 bug，静态层抓到几个、AI 层抓到几个、merge 后三类对照是否成立。这是"双检有价值"的最低证明。

### v0.2 — 鲁棒性强化（系统不裸奔）
**目标：AI 不可用、网络抖、重复评审三场景都稳。**

- `fallback_chain`：本地兜底从"最小说明"升级成更厚的启发式报告，让降级也有信息密度
- `circuit_breaker`：加 cooldown 计时、HALF_OPEN 探针、失败计数衰减
- `cqrs_router`：加 TTL 过期清理（配置 `ttl_days`），换模型链自动失效旧缓存
- `state_machine`：降级路径输出结构对齐正常路径（永远返回完整 `FinalReport`，`ai_report` 字段可选）

**验证基准**：故意断网/填错 key，验证走兜底；重复评审同段代码，第二次毫秒级返回；开 `--no-cache` 强制重跑。

### v0.3 — 扩展与沉淀 SKILL（最终形态）
**目标：多语言 + 输出优化 + 沉淀为可复用 SKILL.md。**

- `static_check`：Go/JS 正则层完善，Go 错误处理（`err != nil` 漏检）、JS `==` 与 `===`、Promise 未 catch
- AI prompt 模板化：`references/prompts/` 下分语言 prompt，降低误报
- 输出格式优化：Markdown 报告（行号定位、风险标签、可合并/修复后合并/阻止合并三档）
- **沉淀 SKILL.md**：把 `skill/` 目录规整为符合 skill 规范的形态，yaml frontmatter + scripts + references，让本系统成为可被其他 agent 调用的技能
- `config.example.yaml` 支持 per-language 自定义阈值

**验证基准**：Go 样本双检通过；SKILL.md 可被独立调用；三样本报告与 v0.1 基线对比，确认无回归。

## 7. 关键设计决策摘要

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 「双检」定义 | 静态快检 + AI 深检 | 两者信息互补，merge 三类对照是核心信息增益 |
| 熔断与 Fallback 关系 | 闸门在前，链在后 | 熔断 OPEN 时整段 AI 不跑，而非边兜底边跑 |
| 迭代节奏 | v0.1 双检优先 → v0.2 鲁棒性 → v0.3 扩展 | 核心能力一步到位，避免 v0.2 重构 |
| 主模型 | 配置驱动，默认 DeepSeek | 不写死，`config.yaml` 定模型链表 |
| 静态层实现 | 纯标准库 ast + 正则 | 不引入第三方依赖，Python `ast` 解析，其他语言正则临时代 |
| CQRS 读写分离 | 全报告缓存 | MVP 简单；增量评审留 v0.3 |
| v0.1 兜底 | 基于静态结果的最小说明（非空 stub） | 降级路径 v0.1 即有信息密度，v0.2 只加厚不返工 |
| 测试形态 | 记录文档（非 pytest） | 契合"迭代日志驱动"风格，不引入测试框架复杂性 |
| 状态机驱动 | 而非 if/else 串联 | 流程可视化、降级路径统一、v0.3 易扩展 |