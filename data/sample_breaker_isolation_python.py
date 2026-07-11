"""熔断器隔离测试 — Python 样本。

用于验证 per-language 熔断器隔离：
故意触发多次失败使 Python 熔断器 OPEN，
验证 Go 熔断器不受影响。
"""

# BUG: mutable default (应被静态层检出)
def build_cache(items=[]):
    for item in items:
        items.append(item)
    return items


# BUG: bare except
def risky_parse(data):
    try:
        return int(data)
    except:
        return 0
