# 双检代码评审系统 执行规则

你正在协助维护一个 AI 代码评审「双检」助手系统。所有评审规则、配置、脚本、日志和测试基线都必须落在本目录的文件中。

## 会话启动

每次处理代码评审相关请求前，先读取：

1. `AGENTS.md`（本文件）
2. `system/status.md`（如果存在）
3. `system/review-rules.json`

如果用户的请求与这些规则冲突，以 `SYSTEM_SPEC.md` 为准；如果用户明确要求临时改变流程，可以执行，但要把原因记录进 `system/logs/`。

如果请求涉及系统功能、规则、脚本或目录结构更新，还要读取 `system/update-logs/README.md` 和最新的 `system/update-logs/YYYY-MM.md`。

## 渐进式披露检索

为了降低上下文消耗，评审和检索必须按渐进式披露执行：

1. 先读轻量入口：`AGENTS.md`、`system/status.md`、`system/review-rules.json`。只有在需要解释规则、修改系统流程或处理冲突时，才细读 `SYSTEM_SPEC.md` 的相关章节。
2. `SYSTEM_SPEC.md` 是完整规约，不是每次评审都要全文装入的素材库。
3. 查缓存时先读 `system/status.md` 的缓存命中率概览，再决定是否深入 `data/.cache/`。
4. 查测试基线时先看 `tests/test_record.md` 的索引结构，只打开相关测试条目对应的 JSON 原文。
5. 禁止为了"保险"预读所有 `data/`、`tests/`、`skill/scripts/` 或全部 `distill/` 文件。

## 意图识别

按自然语言前缀识别任务：

- 用户说"评审""review""检查这段代码"：进入代码评审流程。
- 用户说"缓存""cache"：进入缓存管理流程。
- 用户说"配置""config"：进入配置管理流程。
- 用户说"规则""rule""阈值"：进入评审规则管理流程。
- 用户说"批量""batch""舱壁"：进入批量舱壁隔离评审流程。
- 用户说"健康度""自检""复盘""status"：进入系统健康度自检流程。
- 用户说"趋势""周报""报告""评分""进步"：进入质量趋势报告流程。
- 用户说"记忆""历史""模式""pattern"：进入向量记忆检索流程。
- 用户说"蒸馏""提炼""模式卡片"：进入 Bug 模式蒸馏流程。
- 用户说"对比""认知变化""迭代回顾"：进入系统演进回顾流程。

如果意图模糊，优先给出你理解的操作，并说明将按哪个流程执行；只有在会导致写错位置或覆盖内容时才追问。

## 核心原则

- 文件系统是唯一事实来源。
- `data/.cache/` 是从代码内容派生的 CQRS 缓存，不是事实来源。
- `system/status.md` 是仪表盘，从缓存和熔断器状态生成。
- `system/update-logs/` 专门记录系统功能更新，和日常操作日志 `system/logs/` 分开。
- 每条评审规则只有一个主语言归属，跨语言规则用 `tags` 表达。
- 当前支持语言：`python`、`go`、`javascript`。
- 宁可先快审，不要让代码合并不经评审。
- 评审不是终点，高频出现的 Bug 模式要继续进入蒸馏区，变成可复用资产。
- 熔断器的目标是保护 AI 子系统，不是惩罚它 — 冷却后必须探针验证。

## 代码评审流程

当用户要求评审代码时，按以下流程执行：

1. 读取或接收代码内容。
2. 判断语言和框架上下文。
3. 计算缓存键（sha256(code + lang + model_ver) 全量），先查缓存。
4. 缓存命中 → 直接返回，标记 `source: cache`。
5. 缓存未命中 → 执行静态快检（AST + 正则）。
6. 从 BreakerPool 获取当前语言的熔断器：`pool.get(lang).allow()`。
   - 每个语言独立熔断器（Python 熔断 ≠ Go 熔断）。
   - 允许 → 走三级 AI 降级链（T1 DeepSeek → T2 Qwen → T3 本地兜底）。
   - 阻断（OPEN）→ 直接跳到 T3 本地兜底，不浪费远程调用。
7. 每次模型调用失败喂入对应语言的熔断器，成功后重置。
8. 合并：三路对比（confirmed / rejected / AI-new），计算风险等级。
9. 写入缓存（CQRS 写路径）+ 持久化熔断器状态（`pool._save()`）。
10. 返回 FinalReport + 性能指标（含 ai_tier、breaker_state）。

## 缓存管理流程

当用户要求管理缓存时：

1. 查看 `system/status.md` 的缓存目录大小和命中率。
2. 清除过期条目：超过 TTL（默认 7 天）的缓存文件。
3. 强制失效：当模型链配置变更时，旧缓存自动失效（基于 model_ver）。
4. 重建 `system/status.md` 的缓存相关字段。

## 评审规则管理流程

当用户要求修改评审规则时：

1. 先读 `skill/references/rules/` 下对应语言的 YAML 规则文件。
2. 规则文件是声明式约束，不是代码 — 修改规则不需要改 `static_check.py`。
3. 如果规则文件的 schema 需要扩展，先更新 `system/review-rules.json` 的 schema 定义。
4. 修改后必须跑 `tests/test_record.md` 中的回归基线验证。
5. 记录规则变更到 `system/update-logs/YYYY-MM.md`。

## 系统健康度自检流程

当用户要求"健康度""自检""复盘"时，至少检查三个维度：

| 维度 | 健康的样子 | 不健康的样子 | 不健康时怎么办 |
| --- | --- | --- | --- |
| 缓存命中率 | >50%，响应 <200ms | 命中率 <20% 或缓存膨胀 | 命中率低 → 检查 TTL 是否过短；膨胀 → 缩短 TTL |
| 熔断器状态 | 所有语言 CLOSED，故障 < 阈值 | 任一语言频繁 OPEN 或 HALF_OPEN 振荡 | 频繁断开 → 检查 API Key / 网络；振荡 → 增大 cooldown；`--breaker-reset` 手动重置 |
| 发现质量 | AI 新发现占比 10-50% | AI 全确认（无独立发现）或全否定（信号丢失） | 全确认 → AI 提示词可能太保守；全否定 → 静态层可能过严 |

执行规则：

1. 先运行或读取最近一次 `system/status.md`。
2. 用缓存命中率、熔断器状态、静态/AI 发现比作为基础数据。
3. 将结果写入 `system/reports/YYYY-MM-DD-HHMMSS-health-check.md`。
4. 如果健康检查规则或版本发生变化，同步更新 `system/review-rules.json` 的 `system_version`，并记录到 `system/update-logs/YYYY-MM.md`。

## 蒸馏流程

当用户要求"蒸馏""提炼""整理成卡片"时：

1. 从历史评审记录（`system/logs/` 和 `tests/test_record.md`）中提取反复出现的 Bug 模式。
2. 写入 `distill/patterns/`，一张卡片只讲一个 Bug 模式。
3. 卡片必须包含：核心观点、证据（实际 finding 摘录）、可复用检查方法、触发条件。
4. 跨语言的通用模式写入 `distill/patterns/universal/`，语言特定模式写入 `distill/patterns/<lang>/`。

## 完成后动作

每次评审、修改规则、或系统变更后：

1. 如果评审了新代码，将关键发现写入 `system/logs/YYYY-MM.md`。
2. 如果改动了系统功能、规则、脚本或目录结构，同时追加到 `system/update-logs/YYYY-MM.md`。
3. 如果 cache 目录有变化，更新 `system/status.md` 的缓存统计。
4. 告诉用户评审结论、风险等级、缓存状态和下一步建议。

## 新增语言规则

当需要为新语言添加评审规则时：

1. 在 `skill/references/rules/` 下创建 `<lang>.yaml`。
2. 在 `system/review-rules.json` 的 `languages` 数组中注册。
3. 在 `static_check.py` 中添加对应的 `_<lang>_check()` 函数（遵循现有 Helper 提取模式）。
4. 在 `data/` 下添加该语言的 sample_buggy 和 sample_clean 代码。
5. 在 `tests/test_record.md` 中记录基线。
6. 记录到 `system/update-logs/YYYY-MM.md`。
