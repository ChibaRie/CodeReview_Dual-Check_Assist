"""静态快检层：Python ast + 通用正则。"""
from __future__ import annotations
import ast
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Finding:
    line: int
    kind: str
    severity: str
    message: str


@dataclass
class StaticReport:
    lang: str
    findings: List[Finding] = field(default_factory=list)
    summary: str = ""


def _max_nesting(tree_node: ast.AST) -> int:
    """返回函数体内的最大嵌套深度（≥1；含函数体自身层级）。"""
    def visit(node, d):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            return d
        return max((visit(child, d + 1) for child in body), default=d)
    return visit(tree_node, 0)


def _check_mutable_defaults(node: ast.AST, name: str, defaults: list, findings: list) -> None:
    """检查函数默认参数是否使用了可变对象（list/dict/set）。"""
    for arg in defaults:
        if isinstance(arg, (ast.List, ast.Dict, ast.Set)):
            findings.append(Finding(node.lineno, "mutable_default", "high",
                                   f"函数 {name} 使用可变默认参数"))
        elif isinstance(arg, ast.Call) and getattr(arg.func, "id", "") in ("list", "dict", "set"):
            findings.append(Finding(node.lineno, "mutable_default", "high",
                                   f"函数 {name} 使用可变默认参数"))


def _python_check(code: str, max_fn: int, max_nest: int) -> List[Finding]:
    findings: List[Finding] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [Finding(e.lineno or 1, "syntax_error", "high", f"语法错误: {e.msg}")]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            length = end - node.lineno + 1
            if length > max_fn:
                findings.append(Finding(node.lineno, "long_function", "medium",
                                       f"函数 {node.name} 共 {length} 行，超过 {max_fn}"))
            # Note: approximates cyclomatic complexity by counting branch nodes.
            # Multi-operand BoolOp (e.g. `a and b and c`) is counted as 1, which
            # undercounts; acceptable rough approximation for v0.1.
            branches = sum(1 for n in ast.walk(node)
                           if isinstance(n, (ast.If, ast.For, ast.While,
                                             ast.ExceptHandler, ast.BoolOp,
                                             ast.comprehension)))
            if branches > 10:
                findings.append(Finding(node.lineno, "high_complexity", "medium",
                                       f"函数 {node.name} 圈复杂度约 {branches + 1}"))
            _check_mutable_defaults(node, node.name, node.args.defaults, findings)
            _check_mutable_defaults(node, node.name,
                                    [a for a in node.args.kw_defaults if a is not None], findings)
            if _max_nesting(node) > max_nest:
                findings.append(Finding(node.lineno, "deep_nesting", "medium",
                                       f"函数 {node.name} 嵌套深度超过 {max_nest}"))
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                findings.append(Finding(node.lineno, "bare_except", "medium",
                                       "裸 except 捕获所有异常，建议指定异常类型"))
        elif isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(
                    node.comparators[i], ast.Constant
                ):
                    # `is None` / `is not None` 是 PEP 8 推荐的惯用写法，不过滤
                    if node.comparators[i].value is None:
                        continue
                    findings.append(Finding(node.lineno, "is_literal", "medium",
                                           "用 'is' 比较字面量，应改用 '=='"))
    return findings


def _regex_check(code: str) -> List[Finding]:
    findings: List[Finding] = []
    for i, line in enumerate(code.splitlines(), 1):
        if len(line) > 120:
            findings.append(Finding(i, "long_line", "low",
                                    f"行 {i} 长度 {len(line)}，建议 ≤120"))
        if re.search(r"\bTODO\b|\bFIXME\b", line):
            findings.append(Finding(i, "todo_marker", "low",
                                   "存在 TODO/FIXME 标记"))
    return findings


def static_check(code: str, lang: str, *,
                 max_function_lines: int = 50,
                 max_nesting: int = 4) -> StaticReport:
    """对 code 进行静态检查，返回 StaticReport。"""
    if lang == "python":
        findings = _python_check(code, max_function_lines, max_nesting)
    else:
        findings = []
    findings += _regex_check(code)
    summary = f"发现 {len(findings)} 条静态问题" if findings else "未发现明显静态问题"
    return StaticReport(lang=lang, findings=findings, summary=summary)


if __name__ == "__main__":
    sample = '''def bad(a=[]):
    try:
        x = 1 is 1
    except:
        pass

def very_long_function(p, q, r, s, t, u, v, w):
    if p:
        if q:
            if r:
                if s:
                    if t:
                        pass
    for i in range(10):
        for j in range(10):
            for k in range(10):
                pass
'''
    report = static_check(sample, "python")
    assert len(report.findings) >= 3, report.findings
    print("static_check smoke PASS:", report.summary)

    # --- Inline verification of the two important fixes ---
    # Fix 1: chained comparisons pair each operator with its right operand.
    # `is None` is excluded (PEP 8 singleton idiom); `is b` has no Constant → 0 findings.
    chained = "x = (a is None is b)\n"
    chained_findings = [f for f in _python_check(chained, 50, 4)
                        if f.kind == "is_literal"]
    assert len(chained_findings) == 0, (
        f"expected 0 is_literal findings for chained 'is None is b' "
        f"(None is a singleton, b is a Name), got {len(chained_findings)}: "
        f"{chained_findings}"
    )

    # `is True` should still be flagged (True is not a PEP 8 singleton exception).
    is_true = "if value is True:\n    pass\n"
    true_findings = [f for f in _python_check(is_true, 50, 4)
                     if f.kind == "is_literal"]
    assert len(true_findings) == 1, f"expected 1 for is True, got {len(true_findings)}"

    # Fix 2: keyword-only defaults should be inspected.
    kw_default = "def f(*, a=[]):\n    pass\n"
    kw_findings = [f for f in _python_check(kw_default, 50, 4)
                    if f.kind == "mutable_default"]
    assert len(kw_findings) == 1, (
        f"expected 1 mutable_default finding for kw-only default, "
        f"got {len(kw_findings)}: {kw_findings}"
    )

    print("static_check fix-inline PASS: chained-compare & kw-default verified")

