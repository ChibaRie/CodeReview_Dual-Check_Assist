---
name: dualcheck_code
description: AI 代码评审「双检」助手 — 静态快检 + AI 语义深检，CQRS 缓存，按语言隔离的熔断器池，舱壁隔离，向量记忆，质量趋势报告。当用户说"搭建双检系统""初始化代码评审""安装dualcheck""建一个AI review系统""配置代码审查工具""帮我搭评审环境""给项目加自动评审"时使用本技能。也适用于将现有项目集成自动化代码评审的需求。
---

# DualCheck Code — AI 代码评审双检助手

## 概述

一套完整的 AI 代码评审系统。核心策略：静态规则抓表面问题，AI 解释告警并发现静态层漏掉的逻辑 Bug——两条路径互补，合并后给出三路对比。

**核心能力：** 双检并行、CQRS 缓存(<50ms重复命中)、按语言隔离的熔断器池、三级模型降级链(DeepSeek→Qwen→本地兜底)、舱壁隔离(大文件不阻塞小文件)、向量记忆(Bug模式自动匹配历史)、质量趋势周报。

## 触发条件

用户表示要在某个目录搭建/初始化代码评审系统时触发。典型触发语：
- "在这里搭建双检系统" / "初始化 AI 代码评审" / "帮我装 dualcheck"
- "建一个 automated code review 环境" / "给我项目加个自动评审功能"
- "配置代码审查工具" / "帮我搭评审环境"

## 部署流程

### Step 1: 确认目标目录

询问用户目标目录。默认使用当前工作目录。确认后继续。

### Step 2: 创建目录结构

在目标目录下创建：

```
<项目根>/
├── AGENTS.md                       # AI 执行规则
├── SYSTEM_SPEC.md                  # 系统说明书
├── skill/
│   ├── scripts/                    # 12 个核心 Python 脚本（含 config.py + reviewer.py）
│   └── references/
│       ├── config.example.json     # 模型/熔断器/缓存配置
│       └── rules/                  # 声明式评审规则 YAML
├── data/.cache/                    # CQRS 缓存 + 熔断器持久化
├── system/
│   ├── review-rules.json           # 语言注册表
│   ├── status.md                   # 状态仪表盘
│   ├── logs/                       # 日常操作日志
│   ├── update-logs/                # 系统更新日志
│   └── reports/                    # 健康度报告
├── tests/test_record.md            # 回归测试基线
├── distill/patterns/               # Bug 模式蒸馏
└── iteration/iteration_log.md      # 迭代日志
```

### Step 3: 写入 AGENTS.md

读取 `references/AGENTS.template.md`，写入目标 `AGENTS.md`。此文件是给 AI 执行者看的规则，包含：会话启动→意图识别→核心评审流程→缓存管理→健康度自检→蒸馏流程→新增语言规则。

### Step 4: 写入 SYSTEM_SPEC.md

读取 `references/SYSTEM_SPEC.template.md`，写入目标 `SYSTEM_SPEC.md`。此文件是给人看的系统说明书，包含：系统目标→痛点驱动设计→目录结构→数据契约→评审流程→熔断器规则→蒸馏流程。

### Step 5: 部署核心脚本

将本技能 `scripts/` 目录下所有 .py 文件复制到目标 `skill/scripts/`。

**12 个脚本职责速查：**

| 脚本 | 职责 |
|------|------|
| `app.py` | CLI 入口与编排：`review()` 薄转发到 `Reviewer` 服务、`--batch` 批量评审、`--health`、`--breaker-status`、`--trend-report`、`--vector-stats` |
| `reviewer.py` | **Reviewer 服务**（v0.10 新增）：`Reviewer` 类惰性持有 `_breaker_pool`，`review()` 8 步拆分（`_prepare`→`_read_cache`→`_get_breaker`→`_run_static`→`_vector_match`→`_run_ai`→`_merge_and_store`→`_done_perf`），`merge()`/`_build_prompt()`/`_parse_ai()`/`_risk()` 实例方法。`_get_default()` 无参单例 |
| `config.py` | **配置模块**（v0.10 新增）：4 纯函数——`load_config()`/`default_config_path()`/`resolve_cache_dir()`/`model_ver()`——逐字移植自 app.py，仅依赖 stdlib |
| `static_check.py` | 静态快检：Python AST（7条）、Java 正则（8条）、Go 正则（3条：unchecked_error/defer_in_loop/global_mutable）、JS 正则（4条：var_usage/eqeqeq/debug_log/deep_callback）、通用正则（2条） |
| `circuit_breaker.py` | 熔断器 + BreakerPool：三态(CLOSED→OPEN→HALF_OPEN)、按语言隔离、文件持久化、`create_pool()` 工厂 |
| `cqrs_router.py` | CQRS 读写隔离：SHA256 全量缓存键、TTL 过期清理、访问统计(.stats.json)、信封格式兼容 |
| `fallback_chain.py` | 三级降级链：T1 DeepSeek → T2 Qwen → T3 本地兜底、熔断器闸门、ChainResult 链路追踪 |
| `state_machine.py` | 评审流程状态机：INIT→STATIC→AI_GATE→AI_RUN→MERGE→DONE，支持 blocked 降级路径 |
| `bulkhead.py` | 舱壁隔离：normal pool(10并发/≤500行) + large pool(2并发/>500行)、BulkheadStats 统计 |
| `health_check.py` | 健康度自检：缓存命中率+规则完整性+熔断器状态三维度，生成 system/status.md |
| `vector_store.py` | 向量记忆：sqlite 存储、trigram Jaccard + SimHash 汉明相似度、kind 加权匹配(60%)、去重 |
| `trend_analyzer.py` | 质量趋势：ISO 周分组、评分公式(high=-10/medium=-5/low=-2)、Bug密度、Top类型、改进建议 |

脚本间通过同目录 import 关联。路径约定：`parents[1]`=`skill/`、`parents[2]`=项目根。缓存默认写入 `data/.cache/`（相对于项目根）。

### Step 6: 部署参考配置

将本技能 `references/` 下文件复制到目标 `skill/references/`：

| 文件 | 用途 |
|------|------|
| `config.example.json` | 模型(DeepSeek/Qwen)、熔断器阈值(per_language)、缓存 TTL(7天)、评审阈值 |
| `rules/python.yaml` | Python AST 规则：mutable_default、long_function、high_complexity、deep_nesting、bare_except、is_literal、syntax_error |
| `rules/java.yaml` | Java 专有规则：sql_injection、hardcoded_secret、resource_leak、debug_print、raw_type、naming_convention 等 8 条 |
| `rules/go.yaml` | Go 规则：unchecked_error、defer_in_loop、global_mutable 等 3 条 |
| `rules/javascript.yaml` | JavaScript 规则：var_usage、eqeqeq、debug_log、deep_callback 等 4 条 |
| `rules/universal.yaml` | 通用正则规则：long_line、todo_marker（所有语言生效） |

### Step 7: 写入系统配置

创建 `system/review-rules.json`（语言注册表 + 严重度定义 + 风险等级规则）。参考格式见 `references/review-rules.template.json`。

创建空白基线文件：
- `system/status.md` — 写入 `# System Status\n\n系统尚未运行首次评审。`
- `tests/test_record.md` — 写入 `# 测试基线\n\n待首次评审后填充。`
- `iteration/iteration_log.md` — 写入 `# 迭代日志\n\n## 初始化\n\n- 由 dualcheck_code skill 部署。`

### Step 8: 初始化目录

创建空目录：`data/.cache/`、`system/logs/`、`system/update-logs/`、`system/reports/`、`distill/patterns/universal/`、`distill/patterns/python/`、`distill/patterns/java/`、`distill/patterns/go/`、`distill/patterns/javascript/`。

### Step 9: 运行冒烟测试

按顺序运行验证，全部 PASS 即部署成功：

```bash
cd <目标目录>
python skill/scripts/state_machine.py    # 状态机三态 + 降级路径
python skill/scripts/cqrs_router.py      # 缓存读写 + TTL 过期 + 统计
python skill/scripts/circuit_breaker.py  # 熔断器三态 + 语言隔离 + 持久化
python skill/scripts/fallback_chain.py   # 降级链 T3 兜底 + 熔断跳过
python skill/scripts/bulkhead.py         # 舱壁分类 + 隔离不阻塞
python skill/scripts/vector_store.py     # trigram + hash + 存储检索 + 去重
python skill/scripts/trend_analyzer.py   # 趋势分析 + 格式化 + 空数据
python skill/scripts/static_check.py     # Python AST + Java 正则 + 通用正则
python skill/scripts/config.py           # 配置纯函数单元测试（v0.10 新增）
python skill/scripts/reviewer.py         # Reviewer 服务单元测试（v0.10 新增）
python skill/scripts/health_check.py data/.cache system/status.md  # 健康度生成
python skill/scripts/app.py              # 端到端冒烟（无参数自动运行）
```

**pytest 回归测试（部署后必跑）：**

```bash
cd <目标目录>/tests && python -m pytest -q   # 全部通过（168+）即部署成功
```

测试覆盖 `test_config.py`（9 用例：快照 oracle 逐字移植等价）+ `test_reviewer.py`（3 用例：惰性建池 + `app.review`↔`Reviewer.review` parity）+ 已有 156 基线用例。详见 `tests/test_record.md`。

### Step 10: 输出快速使用指南

部署成功后告知用户：

```bash
# 评审单个文件
python skill/scripts/app.py <文件> --lang python

# JSON 输出 / 强制重新评审 / 批量评审
python skill/scripts/app.py <文件> --lang python --json
python skill/scripts/app.py <文件> --lang python --no-cache
python skill/scripts/app.py --batch data/

# 系统健康度 / 熔断器状态 / 向量记忆 / 趋势周报
python skill/scripts/app.py --health
python skill/scripts/app.py --breaker-status
python skill/scripts/app.py --vector-stats
python skill/scripts/app.py --trend-report
```

**可选：设置 API 密钥启用 AI 深检**
```bash
export DEEPSEEK_API_KEY=your_key       # T1 主模型
export DASHSCOPE_API_KEY=your_key      # T2 降级模型（可选）
```
不设密钥则所有评审走本地兜底（静态层结论 + "AI 暂不可用"标记）。

## 自定义指南

### 添加新语言规则

1. 在 `skill/references/rules/` 创建 `<lang>.yaml`
2. 在 `system/review-rules.json` 的 `languages` 数组注册
3. 在 `static_check.py` 添加 `_<lang>_check()` 函数并在 `static_check()` 中路由
4. 在 `config.example.json` 的 `breaker.per_language` 添加熔断阈值
5. 在 `distill/patterns/` 创建 `<lang>/` 目录

### 常用修改点

| 需求 | 文件 | 位置 |
|------|------|------|
| 调整熔断阈值 | `config.example.json` | `breaker.per_language.<lang>` |
| 修改评审管线逻辑 | `reviewer.py` | `Reviewer.review()` + 8 个私有方法 |
| 修改配置路径解析 | `config.py` | `resolve_cache_dir()` / `default_config_path()` |
| 修改评分公式 | `trend_analyzer.py` | `_quality_score()` |
| 新增修复建议模板 | `vector_store.py` | `_suggest_fix()` hints 字典 |
| 调整舱壁行数阈值 | `app.py` | `--bulkhead-threshold` (默认500) |
| 修改缓存 TTL | `config.example.json` | `cache.ttl_days` |

## 架构原则

- **文件系统是唯一事实来源**。`data/.cache/` 是派生缓存，不是事实来源。
- **声明式规则**：评审阈值和规则在 YAML 文件中，`static_check.py` 只负责执行。
- **渐进式披露**：每次评审先读 AGENTS.md → system/status.md → system/review-rules.json，按需深入。
- **宁可先快审**，不要让代码合并不经评审。
- **高频 Bug 模式进入蒸馏区**，变成可复用资产。
- **熔断器目标是保护 AI 子系统**，不是惩罚它——冷却后必须探针验证。
- **每个语言独立熔断**：Python API 故障不影响 Go 评审。
