"""向量记忆测试 — 除零 Bug 版本 2（周三写的代码，不同文件）。

用于验证：v0.6 向量存储可以匹配到 v1 中已存储的相同 Bug 模式，
输出 "与 X 天前的 Bug 相似度 XX%，当时修复方案：..."。
"""


# BUG: 同样的除零问题（与 v1 结构不同但模式相同）
def safe_division(numerator: float, denominator: float) -> float:
    result = numerator / denominator
    return result


# BUG: 裸 except
def parse_number(text: str):
    try:
        return float(text)
    except:
        return 0.0
