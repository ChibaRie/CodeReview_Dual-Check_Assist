"""舱壁隔离测试 — 小文件样本（模拟 validate_email 函数）。

用于验证：大文件评审时，小文件走 normal pool 不被阻塞，< 3s 返回。
"""


def validate_email(email: str) -> bool:
    """验证邮箱格式是否合法。"""
    import re

    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))
