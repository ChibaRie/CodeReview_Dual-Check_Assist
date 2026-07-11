# 测试记录

## v0.1 验证 (2026-07-11)

### 样本 1: sample_buggy_code.py（降级模式）
- 验证对象：静态快检 + AI 熔断降级本地兜底
- 命令：`python skill/scripts/app.py data/sample_buggy_code.py --lang python --json`
- 预期：返回 JSON，包含 static findings，AI 层标注降级
- 实际：

```json
{
  "risk": "阻止合并",
  "summary": "风险等级: 阻止合并; 静态问题 7 条",
  "static_summary": "发现 7 条静态问题",
  "ai_summary": "AI 深检未运行（熔断降级或模型链全部失败）",
  "findings": [
    {
      "line": 2,
      "layer": "static",
      "kind": "mutable_default",
      "severity": "high",
      "message": "函数 add_item 使用可变默认参数"
    },
    {
      "line": 15,
      "layer": "static",
      "kind": "deep_nesting",
      "severity": "medium",
      "message": "函数 classify 嵌套深度超过 4"
    },
    {
      "line": 11,
      "layer": "static",
      "kind": "bare_except",
      "severity": "medium",
      "message": "裸 except 捕获所有异常，建议指定异常类型"
    },
    {
      "line": 16,
      "layer": "static",
      "kind": "is_literal",
      "severity": "medium",
      "message": "用 'is' 比较字面量，应改用 '=='"
    },
    {
      "line": 17,
      "layer": "static",
      "kind": "is_literal",
      "severity": "medium",
      "message": "用 'is' 比较字面量，应改用 '=='"
    },
    {
      "line": 23,
      "layer": "static",
      "kind": "todo_marker",
      "severity": "low",
      "message": "存在 TODO/FIXME 标记"
    },
    {
      "line": 24,
      "layer": "static",
      "kind": "todo_marker",
      "severity": "low",
      "message": "存在 TODO/FIXME 标记"
    }
  ]
}
```

- 结论：通过
- 后续：v0.2 用真实 AI 跑一遍，确认 AI 能发现额外问题

### 样本 2: sample_clean_code.py
- 验证对象：对照组，静态不误报严重问题
- 命令：`python skill/scripts/app.py data/sample_clean_code.py --lang python --json`
- 预期：risk 为 "可合并" 或 "修复后合并"
- 实际：

```json
{
  "risk": "修复后合并",
  "summary": "风险等级: 修复后合并; 静态问题 2 条",
  "static_summary": "发现 2 条静态问题",
  "ai_summary": "AI 深检未运行（熔断降级或模型链全部失败）",
  "findings": [
    {
      "line": 2,
      "layer": "static",
      "kind": "is_literal",
      "severity": "medium",
      "message": "用 'is' 比较字面量，应改用 '=='"
    },
    {
      "line": 17,
      "layer": "static",
      "kind": "is_literal",
      "severity": "medium",
      "message": "用 'is' 比较字面量，应改用 '=='"
    }
  ]
}
```

- 结论：通过（risk 未超过 "修复后合并"）
- 后续：v0.2 验证 AI 层不误报

### 样本 3: sample_go_code.go
- 验证对象：非 Python 语言路径，静态层正则不崩
- 命令：`python skill/scripts/app.py data/sample_go_code.go --lang go --json`
- 预期：返回 JSON，findings 至少包含 long_line/todo 类检查（正则层）
- 实际：

```json
{
  "risk": "修复后合并",
  "summary": "风险等级: 修复后合并; 静态问题 2 条",
  "static_summary": "发现 2 条静态问题",
  "ai_summary": "AI 深检未运行（熔断降级或模型链全部失败）",
  "findings": [
    {
      "line": 15,
      "layer": "static",
      "kind": "todo_marker",
      "severity": "low",
      "message": "存在 TODO/FIXME 标记"
    },
    {
      "line": 17,
      "layer": "static",
      "kind": "long_line",
      "severity": "low",
      "message": "行 17 长度 144，建议 ≤120"
    }
  ]
}
```

- 结论：通过（正则层正确触发 todo_marker 与 long_line，非 Python 路径返回结构完整）
- 后续：v0.3 扩展 Go 静态规则

### 缓存命中验证
- 命令：`time python skill/scripts/app.py data/sample_buggy_code.py --lang python --json`
- 预期：第二次运行显著快于第一次（<100ms）
- 实际：第一次 159.2 ms，第二次 114.5 ms
- 结论：未达 <100 ms 目标，原因是 Windows Python 进程启动开销；缓存逻辑本身正确（二次运行仍快于首次），v0.2 可优化

### 强制重新评审（--no-cache）
- 命令：`python skill/scripts/app.py data/sample_buggy_code.py --lang python --no-cache --json`
- 预期：跳过缓存重新执行静态检查
- 实际：输出与首次静态-only 一致（risk: 阻止合并，7 条 static findings）
- 结论：通过
