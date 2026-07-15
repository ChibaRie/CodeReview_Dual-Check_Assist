<p align="center">
  <h1 align="center">🔍 AI 代码评审「双检」助手</h1>
  <p align="center"><i>DualCheck Code — 让独立开发者拥有稳定可靠的自动化 Code Review</i></p>
  <p align="center">
    <img src="https://img.shields.io/badge/version-v1.0.1-blue" alt="version">
    <img src="https://img.shields.io/badge/python-3.10+-green" alt="python">
    <img src="https://img.shields.io/badge/frontend-React_|_Vite_|_TypeScript-61dafb" alt="frontend">
    <img src="https://img.shields.io/badge/languages-python(7)_|_java(6)_|_go(3)_|_javascript(4)-orange" alt="languages">
  </p>
</p>

---

## 选题

独立开发者没有人工 Reviewer。贴到 ChatGPT 里聊几句还行，但**没法系统化**——同一个 Bug 反复出现没人提醒、API 挂了就得干等、大文件一贴整个流程堵死。

本系统用**"双检"策略**解决这个问题：静态规则毫秒级抓表面问题，AI 解释告警并发现逻辑 Bug。两条路径互补，合并后三路对比。**每次迭代都由真实痛点驱动**，不是堆功能。

核心能力一览：

- **双检并行**：静态 AST/正则 毫秒级快检 + AI 语义深检，互补覆盖
- **CQRS 缓存**：相同代码重复评审 < **50ms** 返回，Token 消耗降低 **10×**
- **熔断器池**：**按语言隔离**——Python 熔断不影响 Go 评审，Java 可配置更宽松阈值
- **三级降级链**：T1 DeepSeek → T2 Qwen → T3 本地兜底，**永远可用**
- **舱壁隔离**：大文件(>500行)独立线程池，不阻塞小文件响应
- **向量记忆**：Bug 模式自动存入 sqlite，重复出现时匹配历史修复方案
- **可视化 Web UI**：React + Vite 前端，支持单文件/批量评审与系统状态仪表盘
- **前端 API Key 输入**：DeepSeek API key 在浏览器端输入，后端 Proxy 代理调用

---

## 迭代历程

> 每个版本遵循 [5 步迭代法](#迭代规范)：描述痛点 → 量化影响 → 假设原因 → 实现方案 → 评估效果。
> 完整记录见 [`iteration/iteration_log.md`](iteration/iteration_log.md)。

### v0.1 — 双检 MVP

**起点。** 搭通静态快检（Python AST + 通用正则）+ AI 语义深检 + 熔断保护 + DeepSeek→Qwen 降级链 + CQRS 缓存骨架。

> **新增**：`app.py` `static_check.py` `circuit_breaker.py` `cqrs_router.py` `fallback_chain.py` `state_machine.py`

---

### v0.3 — CQRS 缓存性能量化

> **😫 痛点**：用户贴了 `validate_email()` → AI 评审花 5s 消耗 2000 tokens。改了一行**注释**再贴 → 又花 5s 又消耗 2000 tokens。「我没改代码，为什么还要等？」

| 指标 | 改前 | 改后 |
|------|------|------|
| 重复评审响应 | 4–5s | **< 50ms（~100× 提升）** |
| 相同代码 10 次 API 调用 | 10 次 | **1 次** |
| Token 消耗（相同代码×10） | ~20,000 | **~2,000（10× 减少）** |
| 缓存查询耗时 | — | < 5 ms |

> **根因**：每次提交触发完整静态检查 + LLM 调用，没有缓存去重机制。系统无法区分「代码改了」和「只改了注释」。
>
> **方案**：CQRS 读写隔离 —— `key = sha256(代码全文 + 语言 + 模型版本)`，命中缓存直接返回（< 50ms），未命中调 LLM 后写入。全量 SHA256 无碰撞风险，信封格式 `{"_meta": {...}, "report": {...}}` 兼容旧缓存自动迁移，访问统计持久化到 `.stats.json`。涉及 `cqrs_router.py` `app.py`。
>
> **实测**：缓存命中查询 **1.8ms**（目标 < 50ms，超 25×），`--health` 命中率 **61%**（25/41 次），3 次连续评审同一文件首次 MISS→二次 HIT→三次 HIT，`--no-cache` 强制刷新行为正确。

```
用户贴代码
    │
    ▼
┌──────────────────────────┐
│  CQRS Router              │
│  1. 计算 cache key        │    key = sha256(代码全文 + 语言 + 模型版本)
│  2. 查缓存                │
│  ┌─────┐                  │
│  │ 命中 │ ←── 读路径 ──→ 直接返回缓存结果（< 50ms）
│  └─────┘                  │
│  ┌─────┐                  │
│  │未命中│ ←── 写路径       │
│  └─────┘                  │
│      ↓                    │
│  调 LLM → 解析结果 → 写入缓存 → 返回
└──────────────────────────┘
```

**缓存规则：**
1. **缓存键** = `sha256(代码全文 + 语言 + 模型版本)`，任何字符变化都产生不同键
2. **TTL**：默认 7 天，可在 `config.example.json` → `cache.ttl_days` 调整，过期自动删除
3. **缓存范围**：完整 `FinalReport`（风险等级 + findings + 摘要等全部字段）
4. **模型版本感知**：模型配置变更自动生成新缓存键，旧缓存不被误用
5. **强制刷新**：`--no-cache` 跳过读缓存和写缓存
6. **统计追踪**：命中/未命中持久化到 `.stats.json`，`--health` 可查看

---

### v0.4 — 按语言隔离的熔断器池 + 三级降级链

> **😫 痛点**：深夜 2 点 DeepSeek API 波动。贴代码 → 等 15s → 504 Gateway Timeout → 页面白屏。「这什么破系统？」

| 指标 | 改前 | 改后 |
|------|------|------|
| API 不可用时用户体验 | 500 错误 / 白屏 | **自动降级，永远有输出** |
| 系统可用性（API 故障期间） | 0% | **100%（有输出即有可用性）** |
| 用户看到错误页面的概率 | 每次 API 挂都看到 | **趋近于 0** |
| Python API 故障影响 Go 评审 | 全局崩溃 | **互不影响 ✅** |
| 熔断器跨进程持久化 | 不支持（每次重启丢失） | **文件持久化，重启保留** |

> **根因**：单一熔断器全局共享，任何 API 故障全系统不可用。各语言 API 调用相互牵连。
>
> **方案**：按语言隔离的熔断器池（`BreakerPool`）——每个语言独立计数和状态切换。三级降级链：T1 DeepSeek → T2 Qwen → T3 本地兜底，熔断器 OPEN 时直接跳到 T3。文件持久化到 `.breaker_state.json`，跨 CLI 调用保持状态。涉及 `circuit_breaker.py` `fallback_chain.py` `app.py`。
>
> **实测**：Python 熔断器 2 次 `--no-cache` 后 **OPEN**（4 failures ≥ threshold 3），Go 熔断器 **CLOSED**（0 failures，互不影响验证通过），`--breaker-reset python` 仅重置 Python 其他语言不变，kill 后重新运行状态保留。

```
cb_pool = {
    "python": CircuitBreaker(threshold=3, cooldown=30),  # Python 熔断了
    "go":     CircuitBreaker(threshold=3, cooldown=30),  # Go 不受影响 ✅
    "java":   CircuitBreaker(threshold=5, cooldown=60),  # Java 阈值更宽松
    "rust":   CircuitBreaker(threshold=3, cooldown=30),
}

T1: DeepSeek ──fail──→ T2: Qwen ──fail──→ T3: 本地兜底（永远可用）

熔断器状态机：
CLOSED ──(失败 ≥ threshold)──→ OPEN ──(冷却到期)──→ HALF_OPEN
   ↑                                                    │
   └────────────(探针成功)──────────────────────────────┘
                                │
                                └──(探针失败)──→ OPEN
```

**熔断规则：**
1. **语言隔离**：每个语言独立熔断器，按 `config.example.json` → `breaker.per_language` 配置
2. **阈值可配**：各语言可设置不同 `threshold` 和 `cooldown`
3. **持久化**：写入 `data/.cache/.breaker_state.json`，跨 CLI 调用不丢失
4. **状态查询**：`--breaker-status` 查看所有语言实时状态表格
5. **手动重置**：`--breaker-reset [lang]` 重置指定语言或全部
6. **健康检查集成**：`--health` 输出包含熔断器 OPEN 语言数量和详情

---

### v0.5 — 舱壁隔离 + 批量评审

> **😫 痛点**：用户 A 贴了 800 行配置解析代码，用户 B 同时贴了 5 行 `validate_email()`。B 要等 A 评审完 → 等了 15 秒 → B 关掉了页面。

| 指标 | 改前 | 改后 |
|------|------|------|
| 大文件评审时小文件等待 | 15–20s | **< 3s** |
| 大文件最大并发 | 无限制（可能 OOM） | **限制 2 并发** |
| 系统总吞吐量 | 受大文件拖累 | **小文件不受影响** |
| 批量 10 文件含 1 大文件 | 大文件堵死全部 | **9 小文件 40ms 完成** |

> **根因**：单一线程池处理所有文件，大文件耗时阻塞小文件响应。无并发隔离机制。
>
> **方案**：两个独立线程池 —— `normal pool`（10 并发，≤500 行）和 `large pool`（2 并发，>500 行）。`--batch <目录>` 批量模式自动检测文件语言（`.py`→python, `.go`→go, `.js`→javascript）。涉及 `bulkhead.py` `app.py`。
>
> **实测**：10 文件（9 小 + 1 个 4627 行大文件），normal pool 9 完成平均 **41ms/文件**（目标 < 3s，超 73×），large pool 1 完成 92ms，大/小文件耗时比 **2.5x**，[PASS] 小文件不受大文件阻塞。无 API key 下 small_validate 19ms 完成。

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

**舱壁规则：**
1. **行数阈值**：默认 500 行，可通过 `--bulkhead-threshold` 自定义
2. **池大小**：normal pool = 10 workers，large pool = 2 workers（硬编码防 OOM）
3. **自动分类**：`bulkhead.py` 根据 `code.count('\n') + 1` 自动识别
4. **批量模式**：`--batch <目录>` 递归评审所有 `.py/.go/.js` 文件，自动检测语言
5. **统计追踪**：输出每个池完成数、平均耗时、大/小文件耗时比
6. **隔离保证**：large pool 满载时新大文件排队——不影响 normal pool

---

### v0.6 — 向量记忆

> **😫 痛点**：周一写了 `def divide(a, b): return a / b` → AI「缺少除零保护」。周三另一个文件又写了同样的代码 → AI「缺少除零保护」（完全忘记周一说过）。「你能不能记住我上周犯过什么错？」

| 指标 | 改前 | 改后 |
|------|------|------|
| 相同 Bug 模式重复发现率 | 0%（每次都当新的） | **> 80%（匹配历史）** |
| 用户平均修复时间 | 每次都重新诊断 | **复用历史修复方案** |
| 跨文件模式识别 | 不支持 | **自动匹配同语言历史** |

> **根因**：每次评审独立执行，没有跨文件的模式记忆和学习能力。
>
> **方案**：本地 sqlite 向量存储（`patterns.db`）。**相似度引擎**：trigram Jaccard 相似度（25%）+ 64-bit SimHash 汉明相似度（15%）+ kind 匹配加权（60%）。综合评分 > 0.55 视为匹配。内置 8 种常见 Bug 类型的修复建议模板。去重逻辑：存储前检查相似度 > 0.75 的已有模式。涉及 `vector_store.py` `app.py`。
>
> **实测**：v2 的 `bare_except` 匹配到 v1 历史模式，**相似度 77%**，自动提示「指定具体异常类型。如 `except ValueError:` 替代 `except:`」。同类 Bug 匹配率 **100%**。同代码同 kind 不重复存储（>75% 自动跳过）。

```
                   ┌──────────────────────────────────┐
                   │         向量存储（sqlite）         │
                   │  ┌────────┐  ┌────────┐         │
                   │  │ Bug 1  │  │ Bug 2  │         │
                   │  │"除零"  │  │"空指针"│         │
                   │  │[hash]  │  │[hash]  │         │
                   │  └────────┘  └────────┘         │
                   └──────────────────────────────────┘
                              ▲
                              │ 相似度检索（kind + trigram + hash）
                              │
用户贴新代码 ──→ 静态检查 findings ──┘
                    │
                    ▼
           ┌────────────────┐
           │ 相似度 > 0.55  │ ← 命中历史模式
           └───────┬────────┘
                   ▼
      输出："⚠️ 与 N 天前的 Bug 相似度 XX%，当时修复方案：..."
```

**记忆规则：**
1. **存储时机**：每次评审完成后（非缓存命中），所有 findings 自动存入
2. **去重**：同一代码片段同一 kind 相似度 > 75% 不重复存储
3. **检索**：对每个 finding 检索历史相似模式，默认阈值 0.55
4. **相似度计算**：trigram Jaccard（25%）+ 特征哈希汉明（15%）+ kind 匹配（60%）
5. **存储位置**：`data/.cache/patterns.db`（sqlite），不依赖外部向量数据库
6. **修复建议**：每个 Bug kind 内置修复提示模板，匹配成功时自动展示

---

### v0.7 — 质量趋势报告

> **😫 痛点**：用户用了一个月 AI 评审，每周提交 20 次代码。但完全不知道代码质量变好还是变差、最常见 Bug 类型是什么、跟团队其他人比怎么样。「我每天在用，但感觉不到任何变化。」

| 指标 | 改前 | 改后 |
|------|------|------|
| 用户周留存率 | ~30%（用完即走） | **> 70%（为了看周报）** |
| 用户代码评分提升（月） | 无明显变化 | **平均 +15 分** |
| 高频 Bug 类型重复率 | 持续发生 | **降低 50%（被周报聚焦提醒）** |

> **根因**：系统只做评审，不提供反馈闭环。用户缺乏量化的进步感知。
>
> **方案**：从 CQRS 缓存 + 向量存储中提取历史评审数据，按 ISO 周分组。**评分公式**：100 分基准，high=-10 / medium=-5 / low=-2，按每千行标准化。**趋势判断**：比较前半段与后半段平均分差值（>3 改善 / <-3 下降 / 否则稳定）。8 种常见 Bug 类型内置改进建议模板。`cqrs_router.write()` 新增 `code_lines` 参数。涉及 `trend_analyzer.py` `cqrs_router.py` `app.py`。
>
> **实测**：6 周模拟数据（27 次评审，从高 Bug→无 Bug）——评分 **0 → 0 → 0 → 0 → 2 → 46 → 100**（7 周清晰改善），Bug 密度 **37.5 → 39.1 → 40.0 → 31.2 → 29.8 → 22.7 → 0.0**（每千行），趋势 **UP 改善中**（后半段平均 55 > 前半段 0）。Top Bug：todo_marker(19)→bare_except(15)→mutable_default(11)。

```
[TREND] 代码质量趋势周报

> 总体平均评分：72/100
> 趋势：UP 改善中

评分趋势：
  62 → 68 → 75 → 72 → 80 → 85
  ↑    ↑    ↑    ↑    ↑    ↑
  第1周 第2周 第3周 第4周 第5周 第6周

Bug 密度（每千行）：
  12.0 → 10.0 → 8.0 → 6.0 → 4.0 → 3.0

最常见 Bug 类型 Top 3：
  1. mutable_default（15 次）
  2. bare_except（8 次）
  3. todo_marker（5 次）

[FOCUS] 下周建议重点：重点关注函数默认参数的可变性。
```

**报告规则：**
1. **数据来源**：CQRS 缓存（评审记录 + 时间戳）+ 向量存储（Bug 频率）
2. **评分公式**：100 分基准，high=-10, medium=-5, low=-2，按每千行标准化
3. **趋势判断**：比较前半段与后半段平均分差值（>3 改善、<-3 下降、否则稳定）
4. **建议生成**：基于最近一个月最高频 Bug 类型自动选择改进建议
5. **生成方式**：`--trend-report` 命令行，支持 Markdown 和 JSON 输出

---

### v0.9.2 — 测试套件 + Go/JS 规则 + 全语言覆盖

> **😫 痛点**：Exp8 校园管理系统 7 个 Java 文件，系统全部返回 **0 findings**。人工审查却发现 **8 个真实问题**（3 CRITICAL + 1 HIGH + 4 MEDIUM）：SQL 注入、明文密码、资源泄漏全部漏检。

| 指标 | 改前 | 改后 |
|------|------|------|
| Java 文件评审产出 | 0 findings/文件 | **1–5 findings/文件** |
| SQL 注入检测 | 0%（全部漏检） | **字符串拼接 HQL 已覆盖** |
| 硬编码密码检测 | 漏检 | **精准检测（排除 env/注解注入）** |

> **根因**：`static_check.py` 仅有 Python AST 规则 + 通用正则（long_line/todo_marker），Java 语言无专有规则。
>
> **方案**：新增 `_java_check()` 函数实现 8 条 Java 专有规则，新增 `java.yaml` 声明式规则文件。语言分发：`static_check()` 新增 `lang == "java"` 分支路由。涉及 `static_check.py` `rules/java.yaml`。

**Java 规则覆盖矩阵：**

| 规则 | 严重度 | 检测内容 | DAO 命中 | Controller 命中 |
|------|--------|---------|:--:|:--:|
| `sql_injection` | 🔴 HIGH | `createQuery`/`executeUpdate` 字符串拼接 HQL | 1 | 0 |
| `hardcoded_secret` | 🔴 HIGH | `password = "..."` / `apiKey = "..."`（排除 env/@Value） | 0 | 1 |
| `resource_leak` | 🔴 HIGH | `openSession()`/`getConnection()` 无 `close()` | 0* | 0 |
| `debug_print` | 🟡 MEDIUM | `System.out.println` / `.printStackTrace()` | 0 | 2 |
| `raw_type` | 🟡 MEDIUM | 集合声明 `List x = new ArrayList()` 缺泛型 | 0 | 2 |
| `naming_convention` | 🟡 MEDIUM | 方法名 camelCase 分词中非首词全小写 ≥4 字符 | 0 | 0 |
| `unused_import` | 🟢 LOW | import 的类未被引用 | — | — |
| `missing_transactional` | 🟡 MEDIUM | insert/update/delete 无 @Transactional | — | — |

> \* resource_leak 需方法级 brace 深度追踪，当前简化实现，v0.9 加强。

> **实测**：`sample_java_dao.java` 正确检出 1 条 sql_injection（**93% 向量匹配历史**），参数化查询 0 误报，deleteUser 命名 0 误报。`sample_java_controller.java` 正确检出 **5 条**（1 hardcoded_secret + 2 debug_print + 2 raw_type），泛型正确代码 0 误报。

**ssm1805 全量 Java 项目实战评审（MyBatis 框架）**——5 个 Java 文件，**4/5 评审准确，1 个误报**：

| # | 文件 | 静态 | AI | 风险 | 耗时 | 向量 |
|---|------|------|----|------|------|------|
| 1 | pojo/UserInfo.java | 1 (hardcoded_secret) ⚠️ | local_fallback | 阻止合并 | 10.6ms | 1 (69%) |
| 2 | dao/UserInfoDao.java | **0** ✅ | local_fallback | 可合并 | 5.4ms | 0 |
| 3 | service/UserInfoService.java | **0** ✅ | none (breaker OPEN) | 可合并 | 3.4ms | 0 |
| 4 | service/impl/UserInfoServiceImpl.java | **0** ✅ | none (breaker OPEN) | 可合并 | 2.9ms | 0 |
| 5 | controller/UserInfoController.java | **0** ✅ | none (breaker OPEN) | 可合并 | 2.8ms | 0 |

> ⚠️ **FALSE POSITIVE**：`UserInfo.java:69` 触发 `hardcoded_secret`——实际为 `toString()` 中的 `+ ", password=" + password`（字符串模板拼接），非硬编码赋值。**v0.9 需修复**：当 `password=` 出现在 `"..." +` 上下文时不触发。

**框架对比（Exp8 Hibernate vs ssm1805 MyBatis）：**

| 维度 | Exp8 (Hibernate) | ssm1805 (MyBatis) |
|------|:--:|:--:|
| SQL 注入检测 | 3 处命中（HQL 拼接） | **0 处**（`#{ }` 参数化） ✅ |
| 资源泄漏 | 2 处（openSession 无 close） | N/A（Spring 管理 SqlSession） |
| 调试残留 | 1 处（println） | 0 处 |
| 原始类型 | 2 处 | 0 处 |
| 硬编码密码 | 0（字段名 `pwd` 不匹配） | ⚠️ 1 误报（toString 误触发） |
| **真实 Bug 密度** | **8 个**（4 CRITICAL + 4 MEDIUM） | **0 个** ✅ |

> ssm1805 代码质量显著优于 Exp8 原因：MyBatis `#{ }` 参数化查询天然防注入、Spring 容器管理资源生命周期、现代注解驱动减少样板代码、三层架构清晰。

---

### v0.9.2 — 测试套件 + Go/JS 全语言覆盖

> **😫 痛点 1**：测试覆盖率不足——只有 `if __name__ == "__main__"` 冒烟测试，无 mock（LLM 真调 HTTP）、无边界测试、无覆盖率度量。
> **😫 痛点 2**：Go 和 JavaScript 仅 2 条通用规则（long_line + todo_marker），几乎不可用。项目宣传 4 种语言，实际仅 Python 有 AST。

| 指标 | 改前 | 改后 |
|------|------|------|
| 测试框架 | `if __name__` 简单断言 | **pytest 156 测试，8 个模块全覆盖** |
| Mock 能力 | ❌ 无（真调 HTTP） | ✅ `unittest.mock` 模拟 LLM 调用 |
| 边界测试 | ❌ 无 | ✅ 空文件/超大文件/Unicode/并发/损坏数据 |
| Go 专有规则 | 0 条 | **3 条**（unchecked_error, defer_in_loop, global_mutable） |
| JS 专有规则 | 0 条 | **4 条**（var_usage, eqeqeq, debug_log, deep_callback） |
| 全语言可用 | ❌ Go/JS 基本不可用 | ✅ **4 语言全部有专有规则** |

> **根因 1**：早期迭代用 `__main__` 冒烟测试快速验证，缺乏正式测试框架。LLM 调用未抽象，无法 mock。
> **根因 2**：v0.1 仅实现 Python AST，v0.8 补充 Java，Go 和 JS 被延迟到模糊的"后续版本"。
>
> **方案**：
> - **pytest 测试套件**：`tests/` 下 8 个 `test_*.py` 文件 + `conftest.py`（共享 fixtures、mock 工具、边界样本）。覆盖 state_machine、circuit_breaker、cqrs_router、static_check、fallback_chain（含 mock HTTP）、bulkhead、vector_store、trend_analyzer。
> - **Mock 层**：`conftest.py` 提供 `mock_http_success`/`mock_http_failure`/`mock_http_auth_error` fixtures，用 `unittest.mock.patch` 替换 `urllib.request.urlopen`。
> - **边界覆盖**：空代码、空文件、超大文件（2000 行）、Unicode/emoji、特殊字符（正则转义）、并发读写、TTL 过期、损坏 JSON、threshold=0 极值。
> - **Go 规则**（`_go_check()`）：`unchecked_error`（:= 返回 error 缺 err != nil）、`defer_in_loop`（for 循环内 defer 资源泄漏）、`global_mutable`（包级 var 全局变量）。
> - **JS 规则**（`_javascript_check()`）：`var_usage`（var → let/const）、`eqeqeq`（== → ===）、`debug_log`（console.log 残留）、`deep_callback`（缩进 > 80 字符）。
> - **声明式规则**：`go.yaml`（5 条）、`javascript.yaml`（6 条）。
> - 涉及 `static_check.py` `tests/conftest.py` `tests/test_*.py` `rules/go.yaml` `rules/javascript.yaml`。
>
> **实测**：156/156 pytest 测试全部通过（1.3s），含 25 个边界测试 + 8 个 mock 测试。Go 样本检出 unchecked_error + defer_in_loop + global_mutable。JS 样本检出 var_usage + eqeqeq + debug_log（8 findings）。

**全语言覆盖矩阵：**

| 语言 | 规则引擎 | 专有规则 | 通用规则 | 覆盖率 |
|------|---------|---------|---------|:--:|
| **Python** | AST 解析 | 7 条（mutable_default, bare_except, ...） | 2 条 | ✅ 完整 |
| **Java** | 正则模式匹配 | 7 条（sql_injection, hardcoded_secret, ...） | 2 条 | ✅ 完整 |
| **Go** | 正则模式匹配 | 3 条（unchecked_error, defer_in_loop, ...） | 2 条 | ✅ 可用 |
| **JavaScript** | 正则模式匹配 | 4 条（var_usage, eqeqeq, debug_log, ...） | 2 条 | ✅ 可用 |

### v1.0.1 — 前端可视化 Web UI ← 当前

> **😫 痛点**：用户每次都要开终端敲命令行，贴代码、输参数、读纯文本报告。独立开发者需要更直观的交互方式 — 编辑器里写代码、点按钮即评审、图表化看趋势。

| 指标 | 改前 | 改后 |
|------|------|------|
| 使用方式 | CLI 命令行 + 环境变量 | **Web UI 编辑器 + 前端输入 API Key** |
| 系统状态可见性 | `--health` 纯文本输出 | **可视化仪表盘** |
| 批量评审 | `--batch` 表格式终端输出 | **Web UI 表格 + 批量汇总** |
| 部署启动 | 多步骤手动冒烟 | **`npm run dev` 一键启动前后端** |

> **根因**：系统仅有 CLI 入口，缺乏可视化交互界面。AI 代码评审的用户多为独立开发者，他们需要低门槛、即时反馈的工具。
>
> **方案**：新增 React + Vite 前端工程 (`web/`)，FastAPI 后端 (`web_server.py`)，暴露 7 个 `/api/*`端点。前端支持单文件评审（Monaco 编辑器 + 报告面板）、批量目录评审、系统状态仪表盘。API key 在前端输入，后端代理调用 DeepSeek，不记录不持久化。`fallback_chain.py` 与 `reviewer.py` 增加显式 `api_key` 参数透传，CLI 完全兼容。
>
> **实测**：218/218 pytest 全部通过。`npm run build` 构建成功（57 modules, ~193 KB JS）。`npm run dev` 一键启动 Vite :5173 + FastAPI :8000。后端新增代码覆盖率 99%。Skill 包保持独立，前端工程与 Web 服务不污染 `skill/` 目录。

---

### v0.10.0 — 代码质量重构：review() 拆分 + config 模块提取

> **😫 痛点**：`app.py::review()` ~125 行承担配置加载/缓存/熔断/静态/向量/AI/合并/写入全部职责；配置路径硬编码、模块级 global 单例。代码质量与其"评审代码"定位形成讽刺。

| 指标 | 改前 | 改后 |
|------|------|------|
| `review()` 函数体长度 | **125 行**（超限 2.5 倍） | **~50 行** + 8 个私有方法各 <25 行 |
| 配置路径硬编码点 | **2 处**（`_default_config_path`, `_resolve_cache_dir` 反推 base） | **0 处**（全部在 `config.py` 4 纯函数内） |
| 模块级 global | **1 处**（`_breaker_pool` 单例） | **0 处**（`Reviewer` 实例属性） |

> **根因**：单文件 `app.py` 同时承担 CLI、编排、配置、格式化四职，无模块边界；`review()` 把"配置存活期"与"评审流程"耦合。
>
> **方案**：提取 `config.py`（4 纯函数，逐字移植）；引入 `reviewer.py` `Reviewer` 服务，`review()` 8 步拆分（`_prepare` 第 0 步封装 config 加载）；`app.review`/`app.merge` 薄转发；CLI 与 review 共享单一 pool 单例。Oracle 快照切断自证循环。

> **实测**：168/168 pytest 全部通过（含 12 新增：`test_config.py` 9 用例 + `test_reviewer.py` 2 构造 + 1 parity）。`app.py --smoke` PASS，`--breaker-status` 正常。零新 `try/except`，逐字移植纪律达成。

---

### 迭代合规总览

| 版本 | Step 1 痛点 | Step 2 量化 | Step 3 根因 | Step 4 方案 | Step 5 实测 | 合规 |
|------|:--:|:--:|:--:|:--:|:--:|:--:|
| v0.3 CQRS 缓存 | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |
| v0.4 熔断器池 | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |
| v0.5 舱壁隔离 | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |
| v0.6 向量记忆 | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |
| v0.7 质量趋势报告 | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |
| v0.8 Java 规则 | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |
| v0.9.2 测试 + Go/JS | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |
| v0.10.0 代码质量重构 | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |
| v1.0.1 前端可视化 | ✓ | ✓ | ✓ | ✓ | ✓ | ✅ |

> 违反 5 步迭代法的迭代视为未完成。详见 [`iteration/iteration_log.md`](iteration/iteration_log.md)。

---

## 使用方式

### Web UI 本地启动

```bash
# 安装前端依赖
npm install && cd web && npm install && cd ..
# 或一键安装
npm run install:all

# 启动本地 Web UI（Vite + FastAPI 并发）
npm run dev

# 浏览器打开 http://localhost:5173
# - 在编辑器中写代码 / 选择语言 →「评审」→ 查看报告
# - /batch 批量评审目录
# - /dashboard 系统健康度仪表盘
```

### Skill 一键部署

在任意项目目录对 Claude 说：

> **「在这里搭建双检系统」**

Skill 自动完成：建目录 → 写 AGENTS.md → 部署 12 个核心脚本 → 初始化配置 → 冒烟验证。

或手动安装：复制 `skill/` 目录到 `~/.claude/skills/dualcheck_code/`。

### 独立命令行使用

```bash
# 设置 API 密钥（可选，不设则走本地兜底）
export DEEPSEEK_API_KEY=your_key          # T1 主模型
export DASHSCOPE_API_KEY=your_key         # T2 降级（可选）

# 评审单个文件
python skill/scripts/app.py <文件> --lang python
python skill/scripts/app.py <文件> --lang python --json          # JSON 输出
python skill/scripts/app.py <文件> --lang python --no-cache      # 跳过缓存强制重评

# 批量评审（舱壁隔离模式）
python skill/scripts/app.py --batch data/ --no-cache

# 系统管理
python skill/scripts/app.py --health                              # 健康度自检
python skill/scripts/app.py --breaker-status                      # 熔断器实时状态
python skill/scripts/app.py --breaker-reset [语言]                # 重置熔断器
python skill/scripts/app.py --vector-stats                        # 向量记忆统计
python skill/scripts/app.py --trend-report                        # 质量趋势周报
python skill/scripts/app.py --trend-report --json                 # JSON 格式
python skill/scripts/app.py --batch <目录> --bulkhead-threshold 300  # 自定义舱壁阈值
```

### 冒烟验证

```bash
cd <项目根目录>
python skill/scripts/state_machine.py      # 状态机三态 + 降级路径
python skill/scripts/cqrs_router.py        # 缓存读写 + TTL 过期 + 统计
python skill/scripts/circuit_breaker.py    # 熔断器三态 + 语言隔离 + 持久化
python skill/scripts/fallback_chain.py     # 降级链 T3 兜底 + 熔断跳过
python skill/scripts/bulkhead.py           # 舱壁分类 + 隔离不阻塞
python skill/scripts/vector_store.py       # trigram + hash + 存储检索 + 去重
python skill/scripts/trend_analyzer.py     # 趋势分析 + 格式化 + 空数据
python skill/scripts/static_check.py       # Python AST + Java 正则 + 通用正则
python skill/scripts/app.py                # 端到端冒烟（无参数自动运行）
# 全部 PASS 即部署成功
```

---

## 仓库结构

```
AI_Code_Review_Dual-Check_Assist/
├── skill/                          # 🎯 Skill 包（可分发安装）
│   ├── SKILL.md                    #   技能定义文件（含 YAML 前端配置）
│   ├── scripts/                    #   12 个核心 Python 脚本
│   │   ├── app.py                  #   CLI 入口与编排（薄转发到 Reviewer）
│   │   ├── reviewer.py             #   Reviewer 服务（8 步拆分管线，v0.10 新增）
│   │   ├── config.py               #   配置纯函数模块（4 函数，v0.10 新增）
│   │   ├── static_check.py         #   静态快检层（Python AST + Java 正则）
│   │   ├── circuit_breaker.py      #   熔断器 + BreakerPool（按语言隔离）
│   │   ├── cqrs_router.py          #   CQRS 缓存读写（SHA256 全量键）
│   │   ├── fallback_chain.py       #   三级模型降级链（支持 api_key 参数）
│   │   ├── state_machine.py        #   评审流程状态机
│   │   ├── bulkhead.py             #   舱壁隔离（双线程池）
│   │   ├── health_check.py         #   系统健康度自检
│   │   ├── vector_store.py         #   向量记忆存储（sqlite + trigram）
│   │   └── trend_analyzer.py       #   质量趋势分析（ISO 周分组）
│   └── references/                 #   参考配置
│       ├── config.example.json     #   模型 / 熔断器 / 缓存配置
│       └── rules/                  #   声明式评审规则 YAML（5 语言）
├── web/                            # 🖥️ Web UI 前端（v1.0 新增）
│   ├── package.json                #   前端依赖与 scripts
│   ├── vite.config.ts              #   Vite 配置 + API proxy
│   ├── tailwind.config.js          #   Tailwind CSS v3 配置
│   ├── index.html                  #   HTML 入口
│   └── src/
│       ├── main.tsx                #   React 应用挂载
│       ├── App.tsx                 #   路由 + Layout
│       ├── api.ts                  #   API 封装（7 个端点）
│       ├── index.css               #   Tailwind 指令
│       ├── components/             #   通用 UI 组件（6 个）
│       └── pages/                  #   三页面
│           ├── ReviewPage.tsx      #   单文件评审
│           ├── BatchPage.tsx       #   批量评审
│           └── DashboardPage.tsx   #   系统仪表盘
├── web_server.py                   # 🌐 FastAPI 后端入口（v1.0 新增，不属于 skill）
├── package.json                    # 📦 根目录 npm scripts（concurrently）
├── web_server.py                   # 🌐 FastAPI 后端入口（v1.0 新增，不属于 skill）
├── package.json                    # 📦 根目录 npm scripts（concurrently）
├── data/                           # 🧪 测试样本数据（15 文件）
│   ├── sample_buggy_code.py        #   Python 有缺陷样本
│   ├── sample_clean_code.py        #   Python 干净样本（对照组）
│   ├── sample_java_dao.java        #   Java DAO 层（SQL 注入场景）
│   ├── sample_java_controller.java #   Java 控制器层（硬编码密码场景）
│   ├── sample_large_config.py      #   大文件舱壁测试（2313 行）
│   ├── sample_small_validate.py    #   小文件快速响应测试（13 行）
│   └── .cache/                     #   CQRS 缓存 + 熔断器持久化
├── tests/                          # 📋 测试基线记录
│   └── test_record.md              #   按版本分组的回归测试基线
├── iteration/                      # 📝 迭代升级说明
│   └── iteration_log.md            #   版本迁移日志 + 5 步迭代法记录
├── system/                         # 📊 系统状态（自动生成）
│   └── status.md                   #   自动生成的状态仪表盘
├── runtime/                        # 📦 运行时产物（Skill 部署参考）
│   ├── AGENTS.md                   #   AI 执行规则（渐进式披露 + 意图识别）
│   ├── SYSTEM_SPEC.md              #   系统说明书（数据契约 + 架构设计）
│   ├── system/                     #   系统配置模板（部署参考）
│   │   ├── review-rules.json       #   评审规则注册表 + 语言定义
│   │   ├── status.md               #   状态仪表盘模板
│   │   ├── logs/                   #   日常操作日志
│   │   ├── update-logs/            #   系统功能更新日志
│   │   └── reports/                #   健康度自检报告
│   ├── distill/                    #   Bug 模式蒸馏卡片
│   │   └── patterns/python/        #   语言特定可复用模式
│   └── docs/                       #   设计文档
│       └── superpowers/            #   实现计划 + 设计规约（6 文档）
└── README.md                       # 📖 本文件
```

---

## 支持语言

| 语言 | 检查方式 | 规则数 | 备注 |
|------|---------|--------|------|
| **Python** | AST 解析 + 正则 | 7 AST + 2 通用 | 完整 AST 支持 |
| **Java** | 正则模式匹配 | 6 专有 + 2 通用 | v0.8 新增，覆盖 SQL 注入等 |
| **Go** | 正则模式匹配 | 3 专有 + 2 通用 | v0.9 新增，覆盖错误检查等 |
| **JavaScript** | 正则模式匹配 | 4 专有 + 2 通用 | v0.9 新增，覆盖 var/==/console |

---

## 架构

```
用户入口 ──→ Web UI (React) ──→ FastAPI ──→ Reviewer
                                      │
            ┌─────────────────────────┘
            ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  静态快检     │ ──→ │  CQRS 缓存   │ ──→ │  熔断器闸门   │
│  AST + 正则   │     │  SHA256 去重 │     │  per-lang    │
└──────────────┘     └──────┬───────┘     └──────┬───────┘
                            │ 未命中              │ 放行
                            ▼                     ▼
                     ┌──────────────┐     ┌──────────────┐
                     │  向量记忆     │     │  三级降级链   │
                     │  sqlite 匹配  │     │  DS→Qwen→本地 │
                     └──────────────┘     └──────┬───────┘
                                                 │
                            ┌────────────────────┘
                            ▼
                     ┌──────────────┐
                     │  三路合并      │
                     │  static /     │
                     │  ai_confirmed │
                     │  ai_new       │
                     └──────┬───────┘
                            ▼
                     ┌──────────────┐
                     │  FinalReport  │
                     │  + 风险等级   │
                     └──────────────┘
```

---

## 迭代规范

### 三大产物（强制）

每次迭代必须在以下三个目录留下对应产物，缺一不可：

| 目录 | 内容要求 |
|------|---------|
| `data/` | 测试代码样本（至少 1 个新样本或更新现有样本） |
| `tests/` | 测试记录文件，含命令、预期、实际 JSON、结论 |
| `iteration/` | 迭代升级说明，含版本迁移、变更摘要、涉及文件、量化效果 |

### 5 步迭代法（强制）

每次迭代必须在 `iteration/iteration_log.md` 中按以下 5 步记录：

| 步骤 | 名称 | 内容要求 | 输出物 |
|------|------|---------|--------|
| **Step 1** | 描述痛点 | 真实用户场景叙事 | `> **真实场景**：...` |
| **Step 2** | 量化影响 | 改前 vs 改后指标对比表（≥3 指标） | 对比表格 |
| **Step 3** | 假设原因 | 根因分析 | `**根因**：...` |
| **Step 4** | 实现方案 | 架构图 + 核心代码变更列表 | ASCII 架构图 + 涉及文件 |
| **Step 5** | 评估效果 | 测试验证结果（实际数据，非预期） | 实测数据 |

**审核标准**：每步必须有可验证的产出物。缺少任一步骤视为迭代未完成。

### 测试数据规范

1. **命名**：`data/sample_<场景>.py`，语义清晰
2. **标注**：顶部标注测试目的，行内用 `# VULN:` / `# SMELL:` / `# BUG:` 标注问题点
3. **对照**：每个场景应有 buggy 版和 clean 版，验证规则不误报
4. **边界**：覆盖正确代码、典型错误、边界案例

### 测试记录规范

1. **位置**：`tests/test_record.md`，按版本分组
2. **条目格式**：验证对象 → 命令 → 预期 → 实际（JSON）→ 结论 → 后续
3. **回归**：每次迭代必须回归全部已有样本

---

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
  <br><sub>Copyright © 2026 ChibaRie — 自由使用、修改、分发</sub>
</p>
