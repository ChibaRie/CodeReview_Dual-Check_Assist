# 前端可视化设计规约

> 版本：v1.0.1 已实现  
> 日期：2026-07-15  
> 状态：已完成

---

## 1. 背景与目标

当前 DualCheck Code 是纯 Python CLI 工具，用户通过 `python skill/scripts/app.py` 输入代码并查看文本报告。为了让独立开发者拥有更直观、更低门槛的使用体验，本项目增加一个本地 Web UI。

**核心目标**：
- 提供可视化代码评审界面，降低使用门槛。
- 用户在前端输入 DeepSeek API key，后端代理调用模型。
- 第一版覆盖：单文件评审、批量评审、系统状态仪表盘。
- 开发启动方式与常见前端项目一致：`npm run dev`。

**非目标**：
- 本次不涉及 GitHub Pages 静态部署改造。
- 不替代 CLI，CLI 保持完全兼容。

---

## 2. 总体架构

新增 `web/` 目录作为 React + Vite 前端工程，后端新增 `web_server.py` 作为 FastAPI HTTP 入口。

> **重要：`skill/` 目录是独立维护的 Claude Code skill 包，需要随每次蒸馏同步更新。前端可视化工程和后端 Web 服务不属于 skill 包，必须放在项目根目录，避免污染 `skill/`。**

```text
AI_Code_Review_Dual-Check_Assist/
├── skill/                          # 独立 skill 包（保持纯净）
│   ├── SKILL.md                    # skill 定义文件
│   ├── scripts/                    # 12 个核心 Python 脚本
│   │   ├── app.py                  # 现有 CLI（保持兼容）
│   │   ├── reviewer.py             # 现有 Reviewer 服务（复用）
│   │   ├── fallback_chain.py       # 修改：接受 api_key 参数
│   │   └── ...                     # 其他核心脚本
│   └── references/                 # 配置与规则
│       ├── config.example.json
│       └── rules/
├── web/                            # 新增：React + Vite 前端工程
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api.ts                  # 封装 /api/* 调用
│       ├── components/             # 通用组件
│       └── pages/
│           ├── ReviewPage.tsx      # 单文件评审
│           ├── BatchPage.tsx       # 批量评审
│           └── DashboardPage.tsx   # 仪表盘
├── web_server.py                   # 新增：FastAPI HTTP API（项目根目录）
├── package.json                    # 新增：根目录 npm scripts
└── data/.cache/                    # 现有缓存目录（前后端共用）
```

`web_server.py` 运行时导入 `skill.scripts.reviewer` 等模块（当前系统运行时本就依赖这些脚本），但 `web_server.py` 本身不属于 skill 包，不随 skill 分发。

**运行方式**：
- `npm run dev`：通过 `concurrently` 同时启动 Vite 开发服务器（5173）和 FastAPI（8000）。
- FastAPI 由 `python web_server.py` 启动。
- Vite 配置 `proxy`，将 `/api/*` 转发到 `http://127.0.0.1:8000`。
- 前端所有请求均使用相对路径 `/api/...`。

---

## 3. 后端 API 设计

### 3.1 FastAPI 端点

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/review` | 单文件评审 |
| `POST` | `/api/batch` | 批量目录评审 |
| `GET` | `/api/health` | 健康度自检 |
| `GET` | `/api/breaker` | 熔断器状态 |
| `POST` | `/api/breaker/reset` | 重置熔断器 |
| `GET` | `/api/vector/stats` | 向量记忆统计 |
| `GET` | `/api/trend` | 质量趋势报告 |

### 3.2 请求/响应示例

**POST /api/review**

请求：
```json
{
  "code": "def f(a=[]):\n    pass\n",
  "lang": "python",
  "framework": "",
  "api_key": "sk-...",
  "use_cache": true
}
```

响应：
```json
{
  "risk": "修复后合并",
  "summary": "风险等级: 修复后合并; 静态问题 2 条; AI 新发现 1 条",
  "static_summary": "静态检查完成，发现 2 个问题",
  "ai_summary": "AI 确认 1 条，新发现 1 条，否定 0 条",
  "findings": [
    {
      "line": 1,
      "layer": "static",
      "kind": "mutable_default",
      "severity": "medium",
      "message": "默认参数使用了可变对象 []"
    }
  ],
  "_perf": {
    "cache_hit": false,
    "elapsed_ms": 3200,
    "cache_lookup_ms": 0.5,
    "ai_tier": "deepseek",
    "breaker_state": "CLOSED",
    "vector_matches": 0,
    "vector_stored": 1
  }
}
```

### 3.3 API key 传参改造

现有 `FallbackChain` 从 `os.environ` 读取 API key，改造为显式接收：

- `FallbackChain.call(prompt, static_report, api_key: str = "")`
- 传入 `api_key` 时优先使用传入值。
- 未传入时回退到环境变量（保持 CLI 兼容）。

`Reviewer.review` 增加可选参数 `api_key: str = ""`，向下透传给 `_run_ai`。

---

## 4. 前端设计

### 4.1 页面路由

| 路由 | 页面 | 功能 |
|------|------|------|
| `/` | `ReviewPage` | 单文件代码评审（默认首页） |
| `/batch` | `BatchPage` | 批量目录评审 |
| `/dashboard` | `DashboardPage` | 系统状态仪表盘 |

### 4.2 通用组件

- **Layout**：左侧导航栏 + 主内容区。顶部显示当前 API key 是否已输入（仅显示末 4 位）。
- **ApiKeyInput**：密码类型输入框，值保存在 `localStorage`，所有 API 调用自动读取。
- **CodeEditor**：基于 `@monaco-editor/react` 的代码编辑器，支持语法高亮和行号。
- **SeverityBadge**：severity 标签（high 红 / medium 黄 / low 蓝）。
- **FindingCard**：单条 finding 卡片，展示行号、层级、类型、严重度、描述。
- **RiskBanner**：顶部风险等级横幅（阻止合并 / 修复后合并 / 可合并）。
- **PerfFooter**：显示耗时、缓存命中、AI tier、熔断器状态、向量匹配数。

### 4.3 页面详情

**ReviewPage**
- 左侧：代码编辑器 + 语言选择 + 框架输入 + DeepSeek key 输入。
- 右侧：评审报告，包含 `RiskBanner`、摘要、`FindingCard` 列表、`PerfFooter`。
- 操作按钮：「评审」「强制刷新（跳过缓存）」。

**BatchPage**
- 目录输入（支持拖拽选择）。
- 舱壁阈值设置。
- 结果表格：文件名、行数、风险等级、耗时、所在 pool。
- 批量汇总统计：总文件数、总耗时、normal/large pool 平均耗时。

**DashboardPage**
- 缓存命中率卡片。
- 熔断器状态表格（按语言）。
- 向量记忆统计（总模式数、Top Bug 类型）。
- 趋势报告区域（评分趋势、Bug 密度、Top 类型、改进建议）。

---

## 5. 数据流

1. 用户在 UI 输入 DeepSeek API key → 存入 `localStorage`。
2. 用户编辑代码并选择语言 → 点击「评审」。
3. `api.ts` 读取 key → POST `/api/review`。
4. FastAPI 接收请求 → 调用 `Reviewer.review(code, lang, framework, config_path, use_cache, api_key)`。
5. `Reviewer` 内部走现有流程：缓存查询 → 静态检查 → 向量匹配 → 熔断器判断 → AI 深检 → 合并 → 写入缓存/向量存储。
6. 返回 `FinalReport + perf` → 前端渲染。

---

## 6. 错误处理与安全

### 6.1 API key 安全

- 前端输入框类型为 `password`，key 仅保存在 `localStorage`。
- key 只发送给本地后端 `http://127.0.0.1:8000`，不发送到任何第三方。
- 后端接收 key 后仅用于本次 DeepSeek 调用，不记录、不持久化、不打印日志。
- CLI 路径仍优先使用 `DEEPSEEK_API_KEY` 环境变量；未提供时走本地兜底。

### 6.2 错误场景

| 场景 | 前端行为 | 后端行为 |
|------|---------|---------|
| 未输入 API key | 提示「请输入 DeepSeek API key」 | 返回本地兜底结果（T3） |
| DeepSeek API 失败 | 显示「AI 链路降级」警告，仍展示静态报告 | 熔断器记录失败，自动降级到 Qwen/本地兜底 |
| 无法连接本地后端 | 显示「无法连接到本地服务」错误 | — |
| 大文件阻塞 | 显示加载进度/等待提示 | 走 large pool，不阻塞 normal pool |
| 批量中单文件失败 | 表格中该文件显示 ERROR | 捕获异常，继续处理其他文件 |

### 6.3 CORS 与校验

- FastAPI 配置 `CORSMiddleware`，允许 `http://localhost:5173` 等常见 Vite 端口。
- `lang` 必须是 `python/java/go/javascript` 之一。
- `code` 不能为空字符串。

---

## 7. 测试计划

### 7.1 后端测试

| 测试 | 方式 |
|------|------|
| FastAPI 端点 | 使用 `TestClient` 测试 `/api/review`、`/api/batch`、`/api/health` |
| API key 传参 | 验证 `Reviewer.review(api_key=...)` 可覆盖环境变量 |
| CLI 兼容 | 确保现有 `app.py` CLI 测试与冒烟测试仍通过 |
| CORS | 验证本地开发跨域配置正常 |

### 7.2 前端测试

| 测试 | 方式 |
|------|------|
| API 封装 | `api.ts` 单元测试（mock fetch） |
| 组件 | React Testing Library 测试 `ApiKeyInput`、`FindingCard`、`RiskBanner` |
| 页面 | 测试 `ReviewPage` 提交后正确渲染 findings |

### 7.3 端到端验证

1. `npm run dev` 启动前后端。
2. 输入 sample buggy Python 代码。
3. 输入或留空 DeepSeek API key。
4. 点击评审，确认报告正常展示。
5. 切换到 Dashboard，确认熔断器/缓存状态可读取。
6. 批量评审 `data/` 目录，确认表格展示正确。

### 7.4 覆盖率目标

- 后端新增代码：≥80%。
- 前端：核心组件和 API 封装覆盖，UI 复杂交互不强制 80%。

---

## 8. 依赖清单

### 8.1 后端新增

- `fastapi`
- `uvicorn`
- `python-multipart`（预留，批量上传可能用到）

### 8.2 前端

- `react`
- `react-dom`
- `react-router-dom`
- `vite`
- `@monaco-editor/react`
- `concurrently`（devDependencies，根目录使用）

---

## 9. 实现顺序

1. 改造 `fallback_chain.py` 与 `reviewer.py`，支持 `api_key` 参数。
2. 新增项目根目录 `web_server.py`，暴露 FastAPI API。
3. 新增 `web/` 前端工程，完成 `ReviewPage`。
4. 实现 `BatchPage`。
5. 实现 `DashboardPage`。
6. 根目录 `package.json` + Vite proxy + `npm run dev` 脚本。
7. 后端/前端测试补充。
8. 端到端冒烟验证。

---

## 10. 风险与注意事项

- **API key 泄露风险**：虽然只发给本地后端，但仍需在文档中提醒用户不要在共享机器上保存 key。
- **大文件体验**：批量评审大文件时，UI 需提供加载状态和取消机制（后续迭代）。
- **缓存路径**：FastAPI 运行路径需与 CLI 一致，确保共用 `data/.cache/`。
- **并发启动**：`concurrently` 需处理前端先就绪但后端未启动的短暂失败，前端 API 调用应有重试或友好提示。
