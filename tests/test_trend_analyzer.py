"""趋势分析单元测试。v0.9"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from trend_analyzer import (
    TrendReport,
    WeeklySnapshot,
    _quality_score,
    _suggestion,
    _week_key,
    _week_label,
    analyze,
    fmt_trend_json,
    fmt_trend_report,
)

TZ = timezone(timedelta(hours=8))


class TestQualityScore:
    def test_no_findings_max_score(self):
        assert _quality_score([], 100) == 100

    def test_high_deduction(self):
        findings = [{"severity": "high", "kind": "x"}]
        score = _quality_score(findings, 100)
        assert score < 100

    def test_medium_deduction(self):
        findings = [{"severity": "medium", "kind": "x"}]
        score = _quality_score(findings, 100)
        assert score < 100

    def test_low_deduction(self):
        findings = [{"severity": "low", "kind": "x"}]
        score = _quality_score(findings, 100)
        assert score < 100

    def test_normalized_by_lines(self):
        """代码越短，单位扣分越重"""
        s1 = _quality_score([{"severity": "high"}], 10)   # 短代码
        s2 = _quality_score([{"severity": "high"}], 1000)  # 长代码
        assert s1 < s2

    def test_minimum_score_zero(self):
        findings = [{"severity": "high"}] * 100
        assert _quality_score(findings, 10) == 0


class TestWeekKey:
    def test_week_key_format(self):
        dt = datetime(2026, 7, 6, tzinfo=TZ).timestamp()
        assert "2026-W28" in _week_key(dt) or "W27" in _week_key(dt)


class TestSuggestion:
    def test_no_bugs(self):
        assert "暂无" in _suggestion([])

    def test_specific_bug(self):
        s = _suggestion([("mutable_default", 10)])
        assert "可变" in s or "默认" in s or "mutable" in s.lower()


class TestAnalyze:
    def _write_review(self, cache_dir, week_offset, day, findings, lines=80):
        base = datetime(2026, 7, 12, tzinfo=TZ) - timedelta(weeks=week_offset, days=-day)
        ts = base.timestamp()
        report = {
            "risk": "阻止合并" if findings else "可合并",
            "findings": findings,
            "summary": "test",
            "static_summary": "",
            "ai_summary": "",
        }
        envelope = {
            "_meta": {"created_at": ts, "code_lines": lines, "key": f"w{week_offset}_d{day}", "lang": "python"},
            "report": report,
        }
        (cache_dir / f"w{week_offset}_d{day}.json").write_text(json.dumps(envelope), encoding="utf-8")

    def test_empty_cache(self, temp_dir):
        r = analyze(str(temp_dir))
        assert len(r.weeks) == 0
        assert "暂无" in fmt_trend_report(r)

    def test_single_week(self, temp_dir):
        self._write_review(temp_dir, 0, 1, [{"severity": "high", "kind": "x"}])
        self._write_review(temp_dir, 0, 2, [{"severity": "medium", "kind": "y"}])
        r = analyze(str(temp_dir))
        assert len(r.weeks) >= 1

    def test_multi_week_improving(self, temp_dir):
        # Week 2 (older): bad
        for d in range(3):
            self._write_review(temp_dir, 2, d, [
                {"severity": "high", "kind": "mutable_default"},
                {"severity": "medium", "kind": "bare_except"},
            ])
        # Week 1 (newer): better
        for d in range(3):
            self._write_review(temp_dir, 0, d, [])
        r = analyze(str(temp_dir))
        assert len(r.weeks) >= 2
        # newer weeks should have higher scores
        newer = r.weeks[-1]
        older = r.weeks[0]
        assert newer.avg_score >= older.avg_score

    def test_bug_density_calculation(self, temp_dir):
        self._write_review(temp_dir, 0, 1, [
            {"severity": "high", "kind": "x"},
            {"severity": "medium", "kind": "y"},
        ], lines=200)
        r = analyze(str(temp_dir))
        assert r.weeks[0].bug_density > 0

    def test_top_bugs_aggregated(self, temp_dir):
        for d in range(5):
            self._write_review(temp_dir, 0, d, [
                {"severity": "medium", "kind": "bare_except"},
                {"severity": "low", "kind": "todo_marker"},
            ])
        r = analyze(str(temp_dir))
        assert len(r.overall_top_bugs) >= 2

    def test_trend_declining(self, temp_dir):
        """前半段好 → 后半段差 = declining"""
        for d in range(3):
            self._write_review(temp_dir, 3, d, [])  # older: clean
        for d in range(3):
            self._write_review(temp_dir, 0, d, [
                {"severity": "high", "kind": "x"},
            ])  # newer: buggy
        r = analyze(str(temp_dir))
        assert r.overall_trend == "declining"

    # 边界

    def test_old_format_cache(self, temp_dir):
        """兼容无 _meta 的旧缓存格式"""
        old = {"risk": "可合并", "findings": [], "summary": "", "static_summary": "", "ai_summary": ""}
        (temp_dir / "old.json").write_text(json.dumps(old), encoding="utf-8")
        r = analyze(str(temp_dir))
        assert len(r.weeks) >= 1

    def test_corrupted_cache_file(self, temp_dir):
        (temp_dir / "bad.json").write_text("not json", encoding="utf-8")
        r = analyze(str(temp_dir))
        # 不崩溃
        assert r is not None


class TestFormatting:
    def test_fmt_trend_report_empty(self):
        report = TrendReport()
        assert "暂无足够数据" in fmt_trend_report(report)

    def test_fmt_trend_json(self):
        snap = WeeklySnapshot(week_label="2026-W28", week_start="07-06", reviews=3,
                              total_lines=200, total_findings=5, avg_score=75.0)
        report = TrendReport(weeks=[snap], overall_top_bugs=[("test", 3)],
                             overall_avg_score=75.0, overall_trend="improving",
                             suggestion="focus on tests")
        js = fmt_trend_json(report)
        data = json.loads(js)
        assert data["overall_trend"] == "improving"
        assert data["overall_avg_score"] == 75.0
