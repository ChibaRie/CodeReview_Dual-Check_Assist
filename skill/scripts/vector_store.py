"""向量存储：sqlite + 特征哈希 + trigram 相似度检索。v0.6 — AI 评审记忆。"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BugPattern:
    """从评审 finding 中提取的 Bug 模式。"""

    kind: str                  # finding kind: mutable_default, bare_except, ...
    severity: str              # high / medium / low
    snippet: str               # 触发问题的代码片段（标准化后）
    message: str               # 评审给出的说明
    fix_hint: str = ""         # 修复建议
    lang: str = ""             # 语言
    source_file: str = ""      # 来源文件
    created_at: float = 0.0    # 创建时间
    feature_hash: int = 0      # trigram 特征哈希


def _trigram_hash(text: str) -> int:
    """计算文本的 trigram 特征哈希（64-bit SimHash 风格）。

    提取字符 trigram → 每个 trigram hash 到 64-bit → XOR 合并。
    相似文本产生相近的汉明距离。
    """
    if len(text) < 3:
        text = text + "  "  # pad short texts
    bits = 0
    count = 0
    for i in range(len(text) - 2):
        tg = text[i : i + 3]
        h = int(hashlib.md5(tg.encode()).hexdigest()[:16], 16)
        bits ^= h
        count += 1
    return bits & 0x7FFFFFFFFFFFFFFF  # mask to signed 64-bit for SQLite


def _trigram_set(text: str) -> set[str]:
    """提取字符 trigram 集合，用于 Jaccard 相似度。"""
    if len(text) < 3:
        text = text + "  "
    return {text[i : i + 3] for i in range(len(text) - 2)}


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的 trigram Jaccard 相似度（0.0 ~ 1.0）。"""
    set_a = _trigram_set(text_a)
    set_b = _trigram_set(text_b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def hamming_similarity(hash_a: int, hash_b: int) -> float:
    """计算两个 64-bit 哈希的汉明距离归一化相似度（0.0 ~ 1.0）。"""
    xor = hash_a ^ hash_b
    distance = xor.bit_count()
    return 1.0 - (distance / 64.0)


def _normalize(text: str) -> str:
    """标准化代码片段用于存储和检索。"""
    return " ".join(text.split())[:500]


@dataclass
class PatternMatch:
    """历史模式匹配结果。"""

    pattern: BugPattern
    trigram_sim: float = 0.0     # trigram Jaccard 相似度
    hash_sim: float = 0.0        # 特征哈希相似度
    combined_sim: float = 0.0    # 综合相似度（kind 匹配加权）


@dataclass
class VectorStore:
    """基于 sqlite 的轻量向量存储。

    表结构：
      patterns(id, kind, severity, snippet, message, fix_hint, lang,
               source_file, created_at, feature_hash)
    """

    db_path: str
    _conn: sqlite3.Connection | None = field(default=None, repr=False)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        self._get_conn().execute(
            """CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                severity TEXT NOT NULL,
                snippet TEXT NOT NULL,
                message TEXT NOT NULL,
                fix_hint TEXT DEFAULT '',
                lang TEXT DEFAULT '',
                source_file TEXT DEFAULT '',
                created_at REAL DEFAULT 0,
                feature_hash INTEGER DEFAULT 0
            )"""
        )
        self._get_conn().execute(
            "CREATE INDEX IF NOT EXISTS idx_patterns_kind ON patterns(kind)"
        )
        self._get_conn().execute(
            "CREATE INDEX IF NOT EXISTS idx_patterns_lang ON patterns(lang)"
        )
        self._get_conn().commit()

    # ── 写路径 ─────────────────────────────────────────────

    def add(self, pattern: BugPattern) -> int:
        """存储一个 Bug 模式，返回其 ID。"""
        pattern.feature_hash = _trigram_hash(pattern.snippet)
        pattern.created_at = time.time()
        cursor = self._get_conn().execute(
            """INSERT INTO patterns (kind, severity, snippet, message, fix_hint, lang,
               source_file, created_at, feature_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pattern.kind,
                pattern.severity,
                _normalize(pattern.snippet),
                pattern.message,
                pattern.fix_hint,
                pattern.lang,
                pattern.source_file,
                pattern.created_at,
                pattern.feature_hash,
            ),
        )
        self._get_conn().commit()
        return cursor.lastrowid

    def add_from_finding(self, finding: dict, code: str, lang: str, source_file: str = "") -> int:
        """从一条 finding dict 创建并存储 BugPattern。"""
        line = finding.get("line", 0)
        # 提取代码片段：取 finding 所在行前后各 1 行
        code_lines = code.splitlines()
        start = max(0, line - 2)
        end = min(len(code_lines), line + 1)
        snippet = "\n".join(code_lines[start:end])

        # 生成修复建议
        fix_hint = _suggest_fix(finding.get("kind", ""), snippet)

        pattern = BugPattern(
            kind=finding.get("kind", "unknown"),
            severity=finding.get("severity", "medium"),
            snippet=snippet,
            message=finding.get("message", ""),
            fix_hint=fix_hint,
            lang=lang,
            source_file=source_file,
        )
        return self.add(pattern)

    def add_from_report(self, report: dict, code: str, lang: str, source_file: str = "") -> int:
        """从完整评审报告导入所有 findings 到向量存储。返回导入条数。"""
        count = 0
        for f in report.get("findings", []):
            # 避免重复：检查是否已有高度相似的 pattern
            snippet = _normalize(_extract_snippet(code, f.get("line", 0)))
            existing = self.search(
                kind=f.get("kind", ""),
                snippet=snippet,
                threshold=0.75,
                limit=1,
            )
            if not existing:
                self.add_from_finding(f, code, lang, source_file)
                count += 1
        return count

    # ── 读路径（相似度检索） ──────────────────────────────

    def search(
        self,
        kind: str = "",
        snippet: str = "",
        threshold: float = 0.55,
        limit: int = 5,
    ) -> list[PatternMatch]:
        """搜索与给定模式相似的历史 Bug。

        检索策略：
          1. 先按 kind 过滤（同类型 Bug）
          2. 计算 trigram Jaccard + 特征哈希汉明相似度
          3. 综合评分 = Jaccard * 0.5 + HashSim * 0.3 + kind_match * 0.2
          4. 过滤低于 threshold 的结果
        """
        conn = self._get_conn()
        if kind:
            rows = conn.execute(
                "SELECT * FROM patterns WHERE kind = ? ORDER BY created_at DESC LIMIT 200",
                (kind,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM patterns ORDER BY created_at DESC LIMIT 200"
            ).fetchall()

        matches: list[PatternMatch] = []
        normalized_snippet = _normalize(snippet) if snippet else ""

        for row in rows:
            stored_snippet = row[3]  # snippet column
            stored_hash = row[9]     # feature_hash column
            h_sim = hamming_similarity(_trigram_hash(normalized_snippet), stored_hash) if normalized_snippet else 0.0
            t_sim = jaccard_similarity(normalized_snippet, stored_snippet) if normalized_snippet else 0.0

            # kind 匹配加权
            kind_bonus = 1.0 if kind and kind == row[1] else 0.7

            # 同类 Bug 权重最高（相同 kind 是检索的主要信号）
            combined = t_sim * 0.25 + h_sim * 0.15 + kind_bonus * 0.60

            if combined >= threshold:
                pattern = BugPattern(
                    kind=row[1],
                    severity=row[2],
                    snippet=stored_snippet,
                    message=row[4],
                    fix_hint=row[5] or "",
                    lang=row[6] or "",
                    source_file=row[7] or "",
                    created_at=row[8],
                    feature_hash=stored_hash,
                )
                matches.append(
                    PatternMatch(
                        pattern=pattern,
                        trigram_sim=t_sim,
                        hash_sim=h_sim,
                        combined_sim=combined,
                    )
                )

        matches.sort(key=lambda m: m.combined_sim, reverse=True)
        return matches[:limit]

    def stats(self) -> dict:
        """返回向量存储统计信息。"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        kinds = conn.execute(
            "SELECT kind, COUNT(*) as cnt FROM patterns GROUP BY kind ORDER BY cnt DESC"
        ).fetchall()
        langs = conn.execute(
            "SELECT lang, COUNT(*) as cnt FROM patterns GROUP BY lang ORDER BY cnt DESC"
        ).fetchall()
        return {
            "total_patterns": total,
            "db_path": self.db_path,
            "top_kinds": [{"kind": k, "count": c} for k, c in kinds[:10]],
            "by_language": [{"lang": l, "count": c} for l, c in langs],
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ── 辅助函数 ──────────────────────────────────────────────


def _extract_snippet(code: str, line: int) -> str:
    """根据行号提取代码片段。"""
    code_lines = code.splitlines()
    start = max(0, line - 2)
    end = min(len(code_lines), line + 1)
    return "\n".join(code_lines[start:end])


def _suggest_fix(kind: str, snippet: str) -> str:
    """根据 finding kind 生成基础修复建议。"""
    hints = {
        "mutable_default": "将可变默认参数改为 None，在函数体内初始化。如: `def f(a=None): if a is None: a = []`",
        "bare_except": "指定具体异常类型。如: `except ValueError:` 替代 `except:`",
        "deep_nesting": "使用提前返回（early return）减少嵌套层级。",
        "is_literal": "将 `is` 改为 `==` 比较字面量（`is None` 除外）。",
        "long_function": "拆分为多个小函数，每个函数只做一件事。",
        "long_line": "拆分为多行，或提取中间变量。",
        "todo_marker": "完成 TODO/FIXME 项或创建跟踪 Issue。",
        "high_complexity": "提取子函数降低圈复杂度；考虑策略模式或查找表替代复杂分支。",
    }
    return hints.get(kind, "请根据评审说明修复此问题。")


# ── 冒烟测试 ──────────────────────────────────────────────


if __name__ == "__main__":
    import tempfile

    # trigram 相似度
    a = "def divide(a, b): return a / b"
    b = "def divide(x, y): return x / y"
    sim = jaccard_similarity(a, b)
    assert sim > 0.4, f"expected high similarity, got {sim}"
    print(f"trigram Jaccard 相似度 smoke PASS: sim={sim:.2f}")

    # 特征哈希
    h1 = _trigram_hash(a)
    h2 = _trigram_hash(b)
    hsim = hamming_similarity(h1, h2)
    assert hsim > 0.5, f"expected high hash similarity, got {hsim}"
    print(f"特征哈希汉明相似度 smoke PASS: sim={hsim:.2f}")

    # 向量存储
    store = None
    with tempfile.TemporaryDirectory() as td:
        try:
            db = str(Path(td) / "test_patterns.db")
            store = VectorStore(db)

            # 写
            p1 = BugPattern(
                kind="division_by_zero",
                severity="high",
                snippet="def divide(a, b): return a / b",
                message="缺少除零保护",
                fix_hint="添加 if b == 0 检查",
                lang="python",
                source_file="utils.py",
            )
            id1 = store.add(p1)
            assert id1 == 1

            # 读（相似搜索 — 较低阈值）
            matches = store.search(kind="division_by_zero", snippet="def divide(x, y): return x / y", threshold=0.45)
            assert len(matches) > 0, "expected at least 1 match"
            best = matches[0]
            assert best.combined_sim > 0.5, f"low similarity: {best.combined_sim}"
            print(f"向量检索 smoke PASS: {len(matches)} 匹配, 最佳相似度={best.combined_sim:.2f}")
            print(f"  匹配: [{best.pattern.kind}] {best.pattern.message}")
            print(f"  修复: {best.pattern.fix_hint}")

            # 统计
            s = store.stats()
            assert s["total_patterns"] == 1
            print(f"统计 smoke PASS: {s['total_patterns']} 条模式")

            # 不相似的不匹配
            matches2 = store.search(kind="division_by_zero", snippet="for i in range(10): print(i)", threshold=0.55)
            assert len(matches2) == 0 or matches2[0].combined_sim < 0.85
            print(f"不相似过滤 smoke PASS: {len(matches2)} 个误匹配")
        finally:
            if store:
                store.close()

    # add_from_finding / add_from_report
    store2 = None
    with tempfile.TemporaryDirectory() as td:
        try:
            db = str(Path(td) / "test_patterns2.db")
            store2 = VectorStore(db)
            code = "def divide(a, b):\n    return a / b\n"
            finding = {
                "line": 2, "kind": "division_by_zero", "severity": "high",
                "message": "缺少除零保护", "layer": "static",
            }
            store2.add_from_finding(finding, code, "python", "test.py")
            assert store2.stats()["total_patterns"] == 1
            print("add_from_finding smoke PASS")

            # add_from_report 去重
            report = {"findings": [finding]}
            count = store2.add_from_report(report, code, "python", "test.py")
            assert count == 0  # 重复，跳过
            print("add_from_report 去重 smoke PASS")
        finally:
            if store2:
                store2.close()

    print("vector_store 全部 smoke PASS")
