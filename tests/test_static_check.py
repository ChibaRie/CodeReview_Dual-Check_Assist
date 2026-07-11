"""静态检查单元测试 — Python / Java / Go + 边界。v0.9"""
import pytest
from static_check import Finding, StaticReport, _java_check, _python_check, _regex_check, static_check


class TestPythonCheck:
    def test_mutable_default(self, python_buggy_code):
        findings = _python_check(python_buggy_code, 50, 4)
        kinds = [f.kind for f in findings]
        assert "mutable_default" in kinds

    def test_bare_except(self, python_buggy_code):
        findings = _python_check(python_buggy_code, 50, 4)
        kinds = [f.kind for f in findings]
        assert "bare_except" in kinds

    def test_is_literal(self, python_buggy_code):
        findings = _python_check(python_buggy_code, 50, 4)
        kinds = [f.kind for f in findings]
        assert "is_literal" in kinds

    def test_is_none_not_flagged(self):
        """`is None` 不应被 is_literal 规则误报"""
        code = "if value is None:\n    pass\n"
        findings = _python_check(code, 50, 4)
        is_lit = [f for f in findings if f.kind == "is_literal"]
        assert len(is_lit) == 0

    def test_is_true_flagged(self):
        code = "if value is True:\n    pass\n"
        findings = _python_check(code, 50, 4)
        is_lit = [f for f in findings if f.kind == "is_literal"]
        assert len(is_lit) == 1

    def test_chained_comparison(self):
        code = "x = (a is None is b)\n"
        findings = _python_check(code, 50, 4)
        is_lit = [f for f in findings if f.kind == "is_literal"]
        assert len(is_lit) == 0

    def test_clean_code_no_findings(self, python_clean_code):
        findings = _python_check(python_clean_code, 50, 4)
        assert len(findings) == 0

    def test_long_function(self):
        code = "def f():\n" + "    x = 1\n" * 55
        findings = _python_check(code, 50, 4)
        assert any(f.kind == "long_function" for f in findings)

    def test_deep_nesting(self):
        code = "def f():\n if True:\n  if True:\n   if True:\n    if True:\n     if True:\n      pass\n"
        findings = _python_check(code, 50, 4)
        assert any(f.kind == "deep_nesting" for f in findings)

    def test_syntax_error(self):
        code = "def f(:\n    pass\n"
        findings = _python_check(code, 50, 4)
        assert any(f.kind == "syntax_error" for f in findings)

    def test_kw_default_mutable(self):
        code = "def f(*, a=[]):\n    pass\n"
        findings = _python_check(code, 50, 4)
        assert any(f.kind == "mutable_default" for f in findings)

    def test_async_function_detected(self):
        code = "async def f(a=[]):\n    pass\n"
        findings = _python_check(code, 50, 4)
        assert any(f.kind == "mutable_default" for f in findings)


class TestJavaCheck:
    def test_sql_injection(self, java_code):
        findings = _java_check(java_code)
        kinds = [f.kind for f in findings]
        assert "sql_injection" in kinds

    def test_sql_injection_line(self, java_code):
        findings = _java_check(java_code)
        sql = [f for f in findings if f.kind == "sql_injection"]
        assert len(sql) >= 1

    def test_empty_java(self):
        findings = _java_check("")
        assert findings == []

    def test_clean_java(self):
        code = "public class Foo {\n    public void bar() {}\n}\n"
        findings = _java_check(code)
        assert len(findings) == 0


class TestRegexCheck:
    def test_long_line(self):
        code = "x" * 130 + "\n"
        findings = _regex_check(code)
        assert any(f.kind == "long_line" for f in findings)

    def test_todo_marker(self):
        code = "# TODO: fix this\n"
        findings = _regex_check(code)
        assert any(f.kind == "todo_marker" for f in findings)

    def test_fixme_marker(self):
        code = "// FIXME: broken\n"
        findings = _regex_check(code)
        assert any(f.kind == "todo_marker" for f in findings)

    def test_custom_max_line(self):
        code = "x" * 100 + "\n"
        findings = _regex_check(code, max_line_length=80)
        assert any(f.kind == "long_line" for f in findings)


class TestGoCheck:
    def test_unchecked_error(self, go_issues_code):
        from static_check import _go_check
        findings = _go_check(go_issues_code)
        kinds = [f.kind for f in findings]
        assert "unchecked_error" in kinds

    def test_defer_in_loop(self, go_issues_code):
        from static_check import _go_check
        findings = _go_check(go_issues_code)
        kinds = [f.kind for f in findings]
        assert "defer_in_loop" in kinds

    def test_global_mutable(self, go_issues_code):
        from static_check import _go_check
        findings = _go_check(go_issues_code)
        kinds = [f.kind for f in findings]
        assert "global_mutable" in kinds

    def test_empty_go(self):
        from static_check import _go_check
        assert _go_check("") == []

    def test_clean_go(self):
        from static_check import _go_check
        code = "package main\n\nfunc main() {\n\tx := 1\n\tfmt.Println(x)\n}\n"
        assert _go_check(code) == []


class TestJavaScriptCheck:
    def test_var_usage(self, js_issues_code):
        from static_check import _javascript_check
        findings = _javascript_check(js_issues_code)
        kinds = [f.kind for f in findings]
        assert "var_usage" in kinds

    def test_eqeqeq(self, js_issues_code):
        from static_check import _javascript_check
        findings = _javascript_check(js_issues_code)
        kinds = [f.kind for f in findings]
        assert "eqeqeq" in kinds

    def test_debug_log(self, js_issues_code):
        from static_check import _javascript_check
        findings = _javascript_check(js_issues_code)
        kinds = [f.kind for f in findings]
        assert "debug_log" in kinds

    def test_empty_js(self):
        from static_check import _javascript_check
        assert _javascript_check("") == []


class TestStaticCheckDispatch:
    def test_python_dispatch(self, python_buggy_code):
        report = static_check(python_buggy_code, "python")
        assert report.lang == "python"
        assert len(report.findings) >= 3

    def test_java_dispatch(self, java_code):
        report = static_check(java_code, "java")
        assert report.lang == "java"
        assert len(report.findings) >= 1

    def test_go_dispatch(self, go_code):
        report = static_check(go_code, "go")
        assert report.lang == "go"
        kinds = [f.kind for f in report.findings]
        # Go 现在有专有规则 + 通用正则规则
        assert len(kinds) >= 1

    def test_javascript_dispatch(self, js_issues_code):
        report = static_check(js_issues_code, "javascript")
        assert report.lang == "javascript"
        kinds = [f.kind for f in report.findings]
        # JS 专有规则应该触发
        js_kinds = {"var_usage", "eqeqeq", "debug_log"}
        assert any(k in js_kinds for k in kinds)

    def test_typescript_dispatch(self):
        code = "var x: number = 1;\nconsole.log(x);\n"
        report = static_check(code, "typescript")
        assert report.lang == "typescript"
        kinds = [f.kind for f in report.findings]
        assert "var_usage" in kinds or "debug_log" in kinds

    def test_unknown_lang_uses_regex_only(self):
        report = static_check("# TODO: fix\n" + "x" * 130, "rust")
        assert len(report.findings) >= 2  # long_line + todo

    # 边界

    def test_empty_code(self):
        report = static_check("", "python")
        assert report.findings == []

    def test_empty_java(self):
        report = static_check("", "java")
        assert report.findings == []

    def test_empty_go(self):
        report = static_check("", "go")
        assert report.findings == []

    def test_unicode_python(self, unicode_code):
        report = static_check(unicode_code, "python")
        # 不应崩溃，emit 表情和日文正常解析
        assert report.lang == "python"

    def test_very_large_python(self, very_large_code):
        report = static_check(very_large_code, "python", max_function_lines=2000)
        # 不应崩溃
        assert report.lang == "python"

    def test_special_chars_python(self, special_chars_code):
        report = static_check(special_chars_code, "python")
        # 反斜杠、正则字符串等不崩溃
        assert report.lang == "python"
