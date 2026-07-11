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


def _java_check(code: str) -> list[Finding]:
    """Java 静态规则（基于正则模式匹配）。

    覆盖 Exp8 暴露的 P0 缺口：
      - SQL/HQL 注入（字符串拼接构造查询）
      - 硬编码密码/密钥
      - Session/Connection 资源泄漏
      - System.out.println 调试残留
      - 原始类型（List 缺泛型参数）
      - 方法命名反转
    """
    findings: list[Finding] = []
    lines = code.splitlines()

    # ── SQL/HQL 注入：字符串拼接构造查询 ──
    # 模式:  "SELECT/UPDATE/DELETE/INSERT ..." + var 或  "... = '" + var + "'"
    sql_concat = re.compile(
        r'(?:createQuery|executeQuery|executeUpdate|createSQLQuery|session\.createQuery)\s*\(\s*"'
        r'.*?(?:SELECT|UPDATE|DELETE|INSERT|FROM|WHERE)\b',
        re.IGNORECASE,
    )
    for i, line in enumerate(lines, 1):
        if sql_concat.search(line):
            # 检查是否包含字符串拼接（+）
            if "+" in line:
                findings.append(Finding(
                    i, "sql_injection", "high",
                    "SQL/HQL 注入风险：使用字符串拼接构造查询，应用参数化查询（? 占位符 + setParameter）",
                ))

    # ── 硬编码密码/密钥 ──
    secret_patterns = [
        (r'(?:password|passwd|pwd)\s*=\s*"[^"]+"', "high", "硬编码密码"),
        (r'(?:apiKey|api_key|secretKey|secret_key|token)\s*=\s*"[^"]+"', "high", "硬编码密钥/令牌"),
    ]
    for i, line in enumerate(lines, 1):
        for pat, sev, desc in secret_patterns:
            if re.search(pat, line, re.IGNORECASE) and not re.search(r'(?:getenv|environ|System\.getenv|@Value)', line):
                findings.append(Finding(
                    i, "hardcoded_secret", sev,
                    f"{desc}：应将敏感值移至环境变量或配置中心",
                ))

    # ── Session/Connection 资源泄漏 ──
    # 检测：方法内调用了 openSession/getConnection 但同一方法体无 .close()
    session_open = re.compile(r'\.(?:openSession|getCurrentSession|getConnection)\s*\(')
    session_close = re.compile(r'\.close\s*\(\s*\)')
    in_method = False
    brace_depth = 0
    open_line = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # 方法签名检测
        if re.match(r'\s*(?:public|private|protected)\s+(?:\w+\s+)?\w+\s*\(', stripped) and "{" in stripped:
            in_method = True
            brace_depth = 1
            open_line = 0
        elif in_method:
            brace_depth += stripped.count("{") - stripped.count("}")
            if session_open.search(line):
                open_line = i
            if session_close.search(line) and open_line:
                open_line = 0
            if brace_depth <= 0:
                if open_line > 0:
                    findings.append(Finding(
                        open_line, "resource_leak", "high",
                        "Session/Connection 资源泄漏：openSession()/getConnection() 所在方法未调用 close()，"
                        "应用 try-with-resources 或 finally 块确保释放",
                    ))
                in_method = False
                open_line = 0

    # ── System.out.println / printStackTrace 调试残留 ──
    for i, line in enumerate(lines, 1):
        if re.search(r'System\.out\.(?:print|println|printf)\s*\(', line):
            findings.append(Finding(
                i, "debug_print", "medium",
                "调试代码残留：System.out.println 应替换为日志框架（SLF4J/Log4j）",
            ))
        if re.search(r'\.printStackTrace\s*\(\s*\)', line):
            findings.append(Finding(
                i, "debug_print", "medium",
                "调试代码残留：printStackTrace() 应替换为 logger.error() 记录完整堆栈",
            ))

    # ── 原始类型（集合缺泛型参数） ──
    # 检测: List users = new ArrayList()  — 缺泛型
    #       Map m = new HashMap()         — 缺泛型
    raw_decl = re.compile(
        r'\b(?:List|ArrayList|Set|HashSet|Map|HashMap|Collection)\s+\w+\s*=\s*new\s+\w+\s*\(\s*\)',
    )
    raw_new = re.compile(
        r'new\s+(?:ArrayList|HashSet|HashMap|LinkedList|TreeSet)\s*\(\s*\)(?!\s*[;,]|\s*\{)',
    )
    for i, line in enumerate(lines, 1):
        if raw_decl.search(line):
            findings.append(Finding(
                i, "raw_type", "medium",
                "原始类型警告：集合声明缺少泛型参数，应指定类型如 List<String>",
            ))
        elif raw_new.search(line) and "<>" not in line:
            findings.append(Finding(
                i, "raw_type", "medium",
                "原始类型警告：new 集合缺少泛型参数，应使用 <> 菱形运算符",
            ))

    # ── 方法命名不规范（findBydept → findByDept） ──
    # 检测：方法名中某个"词"全小写且 ≥4 字符且不在开头
    # 使用 camelCase 分词: [A-Z][a-z]* 或 [a-z]+
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*(?:public|private|protected)\s+(?:\w+\s+)?(\w+)\s*\(', line)
        if m:
            name = m.group(1)
            words = re.findall(r'[A-Z][a-z]*|[a-z]+', name)
            for w in words[1:]:  # 跳过第一个词（允许全小写）
                if w[0].islower() and len(w) >= 4:
                    findings.append(Finding(
                        i, "naming_convention", "medium",
                        f"方法命名不规范：'{name}' 中 '{w}' 应首字母大写以符合 camelCase",
                    ))

    return findings


def _go_check(code: str) -> list[Finding]:
    """Go 静态规则（基于正则模式匹配）。

    覆盖 Go 常见问题：
      - 未检查错误返回值（err != nil 缺失）
      - defer 在循环中（资源泄漏）
      - 包级可变全局变量
    """
    findings: list[Finding] = []
    lines = code.splitlines()

    # ── 未检查错误返回值 ──
    # Go 中返回 (result, error) 的函数调用后应跟 if err != nil
    for i, line in enumerate(lines, 1):
        # 检测 := 赋值中的 error 返回但后续无 err != nil
        if re.search(r':=\s+[\w.]+\(.*\)', line) and not re.search(r'if\s+err\s*!=\s*nil', line):
            # 检查后续 3 行内是否有 err != nil
            has_check = False
            for j in range(i, min(i + 4, len(lines) + 1)):
                if re.search(r'if\s+err\s*!=\s*nil', lines[j - 1]):
                    has_check = True
                    break
            if not has_check and re.search(r',\s*err\s*:', line):
                findings.append(Finding(
                    i, "unchecked_error", "high",
                    "未检查错误：函数返回 error 但缺少 if err != nil 检查",
                ))

    # ── defer 在循环中 ──
    in_loop = False
    for i, line in enumerate(lines, 1):
        if re.search(r'\bfor\s+', line.strip()):
            in_loop = True
        if in_loop and re.search(r'\bdefer\s+', line):
            findings.append(Finding(
                i, "defer_in_loop", "high",
                "资源泄漏风险：defer 在循环中不会在每次迭代后执行，应封装为函数",
            ))
        if in_loop and line.strip() == "}":
            in_loop = False

    # ── 包级可变变量 ──
    for i, line in enumerate(lines, 1):
        if re.match(r'^\s*var\s+\w+\s+\w+\s*=', line):
            findings.append(Finding(
                i, "global_mutable", "medium",
                "包级可变变量：全局状态降低可测试性，考虑封装到 struct 中",
            ))

    return findings


def _javascript_check(code: str) -> list[Finding]:
    """JavaScript/TypeScript 静态规则（基于正则模式匹配）。

    覆盖 JS/TS 常见问题：
      - var 声明（应用 let/const）
      - == 代替 ===（类型不安全比较）
      - console.log 调试残留
      - 回调嵌套过深
    """
    findings: list[Finding] = []
    lines = code.splitlines()

    # ── var 声明（应用 let/const） ──
    for i, line in enumerate(lines, 1):
        if re.search(r'\bvar\s+\w+\s*=', line):
            findings.append(Finding(
                i, "var_usage", "medium",
                "使用 var 声明变量：var 有函数作用域提升问题，应用 let 或 const",
            ))

    # ── == 代替 === ──
    for i, line in enumerate(lines, 1):
        # 排除 null == undefined 等有意义的 == 使用...使用简单检测
        if re.search(r'[^=!<>]==[^=]', line) and not re.search(r'null\s*==|==\s*null', line):
            findings.append(Finding(
                i, "eqeqeq", "medium",
                "类型不安全的比较：== 会做类型转换，应用 === 避免意外",
            ))

    # ── console.log 调试残留 ──
    for i, line in enumerate(lines, 1):
        if re.search(r'\bconsole\.(?:log|debug|info|warn)\s*\(', line):
            findings.append(Finding(
                i, "debug_log", "medium",
                "调试代码残留：console.log 应在生产代码中移除",
            ))

    # ── 回调嵌套深度检测 ──
    # 简化：计算每行的缩进深度来推断嵌套
    for i, line in enumerate(lines, 1):
        indent = len(line) - len(line.lstrip())
        if indent > 80:  # 20 层 × 4 空格
            findings.append(Finding(
                i, "deep_callback", "medium",
                "回调嵌套过深：考虑使用 async/await 或 Promise 链替代深层回调",
            ))
            break  # 只报告一次

    return findings


def _regex_check(code: str, *, max_line_length: int = 120) -> List[Finding]:
    findings: List[Finding] = []
    for i, line in enumerate(code.splitlines(), 1):
        if len(line) > max_line_length:
            findings.append(Finding(i, "long_line", "low",
                                    f"行 {i} 长度 {len(line)}，建议 ≤{max_line_length}"))
        if re.search(r"\bTODO\b|\bFIXME\b", line):
            findings.append(Finding(i, "todo_marker", "low",
                                   "存在 TODO/FIXME 标记"))
    return findings


def static_check(code: str, lang: str, *,
                 max_function_lines: int = 50,
                 max_nesting: int = 4,
                 max_line_length: int = 120) -> StaticReport:
    """对 code 进行静态检查，返回 StaticReport。"""
    if lang == "python":
        findings = _python_check(code, max_function_lines, max_nesting)
    elif lang == "java":
        findings = _java_check(code)
    elif lang == "go":
        findings = _go_check(code)
    elif lang in ("javascript", "typescript", "js", "ts"):
        findings = _javascript_check(code)
    else:
        findings = []
    findings += _regex_check(code, max_line_length=max_line_length)
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

