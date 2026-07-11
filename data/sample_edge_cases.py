"""边界/边缘案例测试样本 — 用于验证静态层对不易察觉问题的检测。

包含问题类型：
  - 嵌套函数中的可变默认参数
  - 递归缺少基准情形保护
  - 使用可变对象作为类属性默认值
  - 异常吞没（记录后重新抛出但丢失调用栈）
  - 重叠异常处理
  - 混用 async/sync 导致潜在死锁
  - 资源在 finally 之前可能未初始化
"""


# SMELL: 嵌套函数中的可变默认参数
def outer():
    def inner(items=[]):
        items.append(1)
        return items

    return inner()


# SMELL: 递归缺少深度保护
def deep_sum(nested_list):
    total = 0
    for item in nested_list:
        if isinstance(item, list):
            total += deep_sum(item)
        else:
            total += item
    return total


# SMELL: 可变类属性
class UserCache:
    cache = {}  # 所有实例共享！

    def add(self, key, value):
        self.cache[key] = value


# SMELL: 异常吞没但丢失堆栈
def safe_call(func, *args):
    try:
        return func(*args)
    except Exception as e:
        logger.error(f"Call failed: {e}")
        raise RuntimeError("wrapped") from e  # 正确做法，但原异常信息可能不够


# SMELL: 资源未初始化时可能泄漏
def read_config(path):
    f = None
    try:
        f = open(path)
        return f.read()
    finally:
        if f:  # 如果 open 抛异常，f 是 None，不会进这里 — 但这是正确防护
            f.close()
    # 但如果 open 失败，f 可能未定义（虽然代码处理了 None）


# SMELL: 混用同步/异步可能导致阻塞
import asyncio


async def fetch_data(url):
    # 错误：在异步函数中调用同步 requests
    import requests

    resp = requests.get(url)  # 阻塞事件循环！
    return resp.json()


# 正确的异步方式（对照）
async def fetch_data_correct(url):
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()


# 占位
logger = type("log", (), {"error": lambda m: None})()
