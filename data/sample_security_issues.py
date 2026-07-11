"""安全漏洞测试样本 — 用于验证静态层安全规则检测。

包含漏洞类型：
  - 硬编码密钥/令牌
  - SQL 注入（字符串拼接）
  - 路径遍历
  - 不安全反序列化
  - 弱随机数用于安全场景
  - 日志泄露敏感信息
"""

# VULN: 硬编码 API 密钥
API_KEY = "sk-abc123def456ghi789jkl012mno345pqr678stu"
GITHUB_TOKEN = "ghp_1A2b3C4d5E6f7G8h9I0j"


# VULN: SQL 注入 — 字符串拼接
def get_user(user_id: str):
    query = "SELECT * FROM users WHERE id = '" + user_id + "'"
    return execute_query(query)


# VULN: 路径遍历
def read_user_file(filename: str):
    path = "/var/data/users/" + filename
    return open(path).read()


# VULN: 不安全反序列化
import pickle


def load_session(data: bytes):
    return pickle.loads(data)


# VULN: 弱随机数用于 Token 生成
import random
import string


def generate_reset_token():
    return "".join(random.choice(string.ascii_letters) for _ in range(32))


# VULN: 日志泄露敏感信息
import logging


def login(username: str, password: str):
    logging.info(f"User {username} attempting login with password: {password}")
    if authenticate(username, password):
        logging.info(f"Login success for {username}")
        return True
    return False


# 占位函数（不会被执行，仅让 AST 解析不报错）
def execute_query(q):
    pass


def authenticate(u, p):
    return False
