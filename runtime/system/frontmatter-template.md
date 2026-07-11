---
date: 2026-07-12T01:00:00+08:00
type: pattern
topic: code-review
tags: [python, mutable-default, anti-pattern, static-check, ast]
source: data/sample_buggy_code.py (line 2), tests/test_record.md
status: distilled
---

# Python 可变默认参数是 Python 最常见的隐性 Bug 来源之一

## 核心观点

函数默认参数使用可变对象（list/dict/set）时，该对象在函数定义时创建一次并被所有调用共享。
这会导致状态在调用之间累积，产生难以追踪的 Bug。静态检查可以在毫秒级精确捕获此类问题。

## 实际发现证据

来自 sample_buggy_code.py（v0.1 E2E 基线验证）：

```python
# BUG: mutable default argument
def add_item(item, cache=[]):  # ← 静态层命中：line 2, kind=mutable_default, severity=high
    cache.append(item)
    return cache
```

来自测试基线的确认：该 finding 在 v0.1 全部 3 轮验证中稳定命中（率 100%）。

## 可复用检查方法

### 静态规则（AST 层）

检查 `FunctionDef` 节点的 `args.defaults` 和 `args.kw_defaults`：
- 如果默认值是 `ast.List`、`ast.Dict`、`ast.Set` 节点 → 触发
- 如果默认值是 `ast.Call` 且调用名为 `list`/`dict`/`set` → 触发
- 这覆盖了 `def f(a=[])` 和 `def f(a=list())` 两种写法

### AI 语义层验证问题

- "这个函数是否被多次调用？如果是，默认参数的状态累积是否会导致错误？"
- "修改默认参数后，下一次调用是否会看到上一次的副作用？"

## 修复模式

```python
# ❌ 错误写法
def add_item(item, cache=[]):
    cache.append(item)
    return cache

# ✅ 正确写法
def add_item(item, cache=None):
    if cache is None:
        cache = []
    cache.append(item)
    return cache
```

## 触发条件

当你看到任何 Python 函数的默认参数是 `[]`、`{}`、`set()` 或 `list()`/`dict()`/`set()` 调用时，立即怀疑这是一个 bug，除非能证明该函数在整个生命周期内只被调用一次。
