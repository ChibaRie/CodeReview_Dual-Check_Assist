"""性能问题测试样本 — 用于验证静态层性能规则检测。

包含问题类型：
  - N+1 查询模式
  - 无界列表累积
  - 循环内重复属性访问
  - 缺充分页的批量查询
  - 不必要的深拷贝
  - 长函数（超过 50 行阈值）
"""

import copy


# SMELL: N+1 查询模式
def get_orders_with_items_v1(order_ids):
    orders = []
    for oid in order_ids:
        order = fetch_order(oid)
        order["items"] = fetch_items(oid)
        orders.append(order)
    return orders


# BETTER: 批量查询（对照）
def get_orders_with_items_v2(order_ids):
    orders = fetch_orders_batch(order_ids)
    items_map = fetch_items_batch(order_ids)
    for order in orders:
        order["items"] = items_map.get(order["id"], [])
    return orders


# SMELL: 循环内不必要的深拷贝
def process_records(records):
    results = []
    for r in records:
        snapshot = copy.deepcopy(r)
        snapshot["processed"] = True
        snapshot["timestamp"] = now()
        results.append(snapshot)
    return results


# SMELL: 无界列表累积（无分页）
def list_all_transactions(user_id):
    cursor = db_cursor()
    cursor.execute(f"SELECT * FROM transactions WHERE user_id = {user_id}")
    rows = cursor.fetchall()
    result = []
    for row in rows:
        result.append(format_transaction(row))
    return result  # 可能返回数十万条


# SMELL: 循环内重复属性访问
def compute_stats(items):
    total = 0
    for i in range(len(items)):
        item = items[i]
        total += item.get_price() * item.get_quantity()
        item.set_total(total)
    return total


# SMELL: 函数过长（模拟 — 实际阈值 50 行）
def monolithic_report_generator(data, config, formatter, output_path):
    validated = []
    for d in data:
        if d is not None and d.get("active", False):
            validated.append(d)

    transformed = []
    for v in validated:
        t = {}
        t["id"] = v.get("id")
        t["name"] = v.get("name", "unknown").upper()
        t["score"] = v.get("score", 0) * config.get("score_multiplier", 1.0)
        transformed.append(t)

    aggregated = {}
    for t_item in transformed:
        key = t_item["name"][:1]
        aggregated.setdefault(key, []).append(t_item)

    report_lines = ["# Report", ""]
    for key, items in sorted(aggregated.items()):
        report_lines.append(f"## {key}")
        for item in items:
            report_lines.append(f"- {item['name']}: {item['score']}")
        report_lines.append("")

    final = "\n".join(report_lines)
    formatted = formatter(final)
    return formatted


# 占位函数
def fetch_order(oid):
    return {}


def fetch_items(oid):
    return []


def fetch_orders_batch(ids):
    return []


def fetch_items_batch(ids):
    return {}


def now():
    return "2026-01-01"


def db_cursor():
    return type("cur", (), {"execute": lambda s: None, "fetchall": lambda: []})()


def format_transaction(row):
    return row
