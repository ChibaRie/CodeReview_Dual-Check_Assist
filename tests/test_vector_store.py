"""向量存储单元测试。v0.9"""
import time
from pathlib import Path

import pytest
from vector_store import (
    BugPattern,
    VectorStore,
    _normalize,
    _trigram_hash,
    _trigram_set,
    hamming_similarity,
    jaccard_similarity,
    _suggest_fix,
)


class TestTrigramSimilarity:
    def test_identical_texts(self):
        assert jaccard_similarity("def divide(a,b): return a/b", "def divide(a,b): return a/b") == 1.0

    def test_similar_texts(self):
        sim = jaccard_similarity("def divide(a, b): return a / b", "def divide(x, y): return x / y")
        assert sim > 0.4

    def test_different_texts(self):
        sim = jaccard_similarity("def divide(a,b): return a/b", "for i in range(10): print(i)")
        assert sim < 0.3

    def test_empty_text(self):
        sim = jaccard_similarity("", "")
        assert sim == 0.0

    def test_short_text_padded(self):
        sim = jaccard_similarity("ab", "ab")
        assert sim >= 0.0  # 不崩溃


class TestTrigramHash:
    def test_deterministic(self):
        assert _trigram_hash("hello") == _trigram_hash("hello")

    def test_similar_texts_close_hash(self):
        h1 = _trigram_hash("def divide(a, b): return a / b")
        h2 = _trigram_hash("def divide(x, y): return x / y")
        assert hamming_similarity(h1, h2) > 0.5


class TestVectorStore:
    def test_add_and_search(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        store.add(BugPattern(
            kind="bare_except", severity="medium",
            snippet="def f(): try: pass\nexcept: pass",
            message="裸 except", fix_hint="指定异常类型",
            lang="python", source_file="test.py",
        ))
        matches = store.search(kind="bare_except", snippet="def g(): try: pass\nexcept: pass")
        assert len(matches) >= 1
        store.close()

    def test_search_no_results(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        matches = store.search(kind="unknown", snippet="nothing")
        assert matches == []
        store.close()

    def test_add_from_finding(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        code = "def f():\n    try:\n        pass\n    except:\n        pass\n"
        finding = {"line": 4, "kind": "bare_except", "severity": "medium", "message": "裸 except"}
        store.add_from_finding(finding, code, "python", "test.py")
        assert store.stats()["total_patterns"] == 1
        store.close()

    def test_add_from_report_dedup(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        code = "def f():\n    try:\n        pass\n    except:\n        pass\n"
        finding = {"line": 4, "kind": "bare_except", "severity": "medium", "message": "裸 except"}
        report = {"findings": [finding]}
        # 首次
        c1 = store.add_from_report(report, code, "python", "test.py")
        assert c1 == 1
        # 重复
        c2 = store.add_from_report(report, code, "python", "test.py")
        assert c2 == 0
        store.close()

    def test_stats(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        store.add(BugPattern(kind="a", severity="high", snippet="x", message="m", lang="py"))
        store.add(BugPattern(kind="b", severity="low", snippet="y", message="n", lang="py"))
        s = store.stats()
        assert s["total_patterns"] == 2
        assert len(s["top_kinds"]) == 2
        store.close()

    def test_close_and_reopen(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        store.add(BugPattern(kind="test", severity="low", snippet="code", message="msg", lang="py"))
        store.close()
        # reopen
        store2 = VectorStore(db)
        assert store2.stats()["total_patterns"] == 1
        store2.close()

    # 边界

    def test_empty_db_search(self, temp_dir):
        db = str(temp_dir / "empty.db")
        store = VectorStore(db)
        assert store.search(kind="x", snippet="y") == []
        store.close()

    def test_empty_snippet(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        store.add(BugPattern(kind="t", severity="low", snippet="code", message="m"))
        matches = store.search(kind="t", snippet="")  # 空 snippet 不崩溃
        store.close()

    def test_unicode_snippet(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        store.add(BugPattern(kind="x", severity="low", snippet="你好世界 🚀", message="测试"))
        matches = store.search(kind="x", snippet="你好世界")
        assert len(matches) >= 1
        store.close()

    def test_many_patterns(self, temp_dir):
        db = str(temp_dir / "test.db")
        store = VectorStore(db)
        for i in range(50):
            store.add(BugPattern(kind=f"k{i%5}", severity="low", snippet=f"code_{i}", message=f"msg_{i}"))
        assert store.stats()["total_patterns"] == 50
        store.close()


class TestSuggestFix:
    def test_known_kinds(self):
        for kind in ["mutable_default", "bare_except", "deep_nesting", "is_literal",
                      "long_function", "long_line", "todo_marker", "high_complexity"]:
            hint = _suggest_fix(kind, "")
            assert len(hint) > 10

    def test_unknown_kind(self):
        hint = _suggest_fix("weird_bug", "")
        assert "评审说明" in hint
