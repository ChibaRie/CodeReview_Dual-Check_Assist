"""向量记忆测试 — 除零 Bug 版本 1（周一写的代码）。

用于验证：v0.6 向量存储可以将此 Bug 模式存入历史，
后续相同模式的代码能匹配到历史记录。
"""


# BUG: 缺少除零保护
def divide(a: float, b: float) -> float:
    return a / b


# BUG: 可变默认参数
def calculate_ratio(values: list = []) -> float:
    total = sum(values)
    return total / len(values) if values else 0.0
