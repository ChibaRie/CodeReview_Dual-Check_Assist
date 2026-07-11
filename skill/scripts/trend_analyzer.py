"""质量趋势分析器：从缓存+向量存储生成周报/趋势报告。v0.7"""
from __future__ import annotations
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path

TZ = timezone(timedelta(hours=8))


@dataclass
class WeeklySnapshot:
    """一周的质量快照。"""

    week_label: str = ""          # "2026-W27"
    week_start: str = ""          # "07-06"
    reviews: int = 0              # 评审次数
    total_lines: int = 0          # 评审代码总行数
    total_findings: int = 0       # findings 总数
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    scores: list[int] = field(default_factory=list)  # 每次评审的质量分
    avg_score: float = 0.0
    bug_density: float = 0.0      # 每千行 findings 数
    top_bugs: list[tuple[str, int]] = field(default_factory=list)  # [(kind, count)]


@dataclass
class TrendReport:
    """完整的趋势报告。"""

    weeks: list[WeeklySnapshot] = field(default_factory=list)
    overall_top_bugs: list[tuple[str, int]] = field(default_factory=list)
    overall_avg_score: float = 0.0
    overall_trend: str = ""       # "improving" / "stable" / "declining"
    suggestion: str = ""


def _week_key(ts: float) -> str:
    """Unix 时间戳 → ISO 周键 '2026-W27'。"""
    dt = datetime.fromtimestamp(ts, tz=TZ)
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _week_label(wk: str) -> str:
    """'2026-W27' → '07-06'（该周一的月-日）。"""
    try:
        year, wnum = wk.split("-W")
        # ISO week 1 = first week with Thursday in new year
        jan4 = datetime(int(year), 1, 4, tzinfo=TZ)
        start = jan4 - timedelta(days=jan4.isoweekday() - 1)
        target = start + timedelta(weeks=int(wnum) - 1)
        return target.strftime("%m-%d")
    except Exception:
        return wk


def _quality_score(findings: list[dict], code_lines: int) -> int:
    """根据 findings 和代码行数计算质量分数（0-100）。

    扣分权重：high=-10, medium=-5, low=-2
    按每千行标准化：实际扣分 = Σ扣分 × (1000 / max(lines, 10))
    最低 0 分。
    """
    if not findings:
        return 100
    deductions = 0
    for f in findings:
        sev = f.get("severity", "low")
        if sev == "high":
            deductions += 10
        elif sev == "medium":
            deductions += 5
        else:
            deductions += 2
    # 标准化到每千行
    normalized = deductions * (1000.0 / max(code_lines, 10))
    return max(0, int(100 - normalized))


def _suggestion(top_bugs: list[tuple[str, int]]) -> str:
    """根据最常见的 Bug 类型生成建议。"""
    if not top_bugs:
        return "暂无足够数据生成建议，请继续使用评审系统积累数据。"

    kind, count = top_bugs[0]
    tips = {
        "mutable_default": "重点关注函数默认参数的可变性——这是你最常犯的错误。每次定义函数前先问自己：'这个默认值可变吗？'",
        "bare_except": "异常处理需要更精确——避免裸 except，指定具体异常类型可以让你更快定位问题。",
        "deep_nesting": "代码嵌套过深是复杂度的信号——尝试使用提前返回（early return）或提取辅助函数来降低嵌套。",
        "is_literal": "用 'is' 比较字面量是一个常见陷阱——记住 PEP 8：只有 None 应该用 'is' 比较。",
        "long_function": "长函数是技术债务的温床——尝试将大函数拆分为职责单一的小函数，每个不超过 30 行。",
        "long_line": "过长的代码行降低可读性——考虑换行或提取中间变量来缩短行长度。",
        "todo_marker": "TODO/FIXME 标记在积累——定期清理这些标记，或将其转换为正式的 Issue 跟踪。",
        "high_complexity": "高圈复杂度的函数难以测试和维护——考虑使用查找表、策略模式或提取子函数来简化逻辑。",
    }
    tip = tips.get(kind, f"建议重点解决 '{kind}' 类型的问题——这是你代码中最频繁出现的 Bug 模式。")
    return f"[FOCUS] 下周建议重点：{tip}（本月出现 {count} 次）"


# ── 核心分析函数 ──────────────────────────────────────────


def analyze(cache_dir: str, vector_db_path: str = "") -> TrendReport:
    """从 CQRS 缓存 + 向量存储生成趋势报告。

    Args:
        cache_dir: CQRS 缓存目录（含 .json 缓存文件）
        vector_db_path: 向量存储 sqlite 路径（可选）
    """
    cp = Path(cache_dir)
    if not cp.exists():
        return TrendReport()

    # ── 1. 扫描缓存文件获取历史评审记录 ──
    weeks_data: dict[str, list[dict]] = defaultdict(list)  # week_key → [review_records]

    for f in cp.glob("*.json"):
        if f.name.startswith("."):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        # 兼容新旧格式
        if "_meta" in data:
            created = data["_meta"].get("created_at", f.stat().st_mtime)
            report = data.get("report", data)
            meta = data["_meta"]
        else:
            created = f.stat().st_mtime
            report = data
            meta = {}

        wk = _week_key(created)
        findings = report.get("findings", [])
        # 估算代码行数：从缓存 key 反推（不可靠），使用 _meta.lang 或默认估算
        # 实际行数存储为 _meta 中的 code_lines 字段（v0.7+ 写入时添加）
        code_lines = meta.get("code_lines", 50)  # fallback 估算

        weeks_data[wk].append({
            "created": created,
            "findings": findings,
            "risk": report.get("risk", ""),
            "code_lines": code_lines,
            "file": meta.get("key", f.name)[:12],
        })

    if not weeks_data:
        return TrendReport()

    # ── 2. 计算每周快照 ──
    snapshots: list[WeeklySnapshot] = []
    all_bug_kinds: defaultdict[str, int] = defaultdict(int)

    for wk in sorted(weeks_data.keys()):
        records = weeks_data[wk]
        snap = WeeklySnapshot(week_label=wk, week_start=_week_label(wk))
        snap.reviews = len(records)

        bug_kinds: defaultdict[str, int] = defaultdict(int)

        for rec in records:
            lines = rec["code_lines"]
            findings = rec["findings"]
            snap.total_lines += lines
            snap.total_findings += len(findings)
            for f in findings:
                sev = f.get("severity", "low")
                if sev == "high":
                    snap.high_count += 1
                elif sev == "medium":
                    snap.medium_count += 1
                else:
                    snap.low_count += 1
                kind = f.get("kind", "unknown")
                bug_kinds[kind] += 1
                all_bug_kinds[kind] += 1

            score = _quality_score(findings, max(lines, 1))
            snap.scores.append(score)

        snap.avg_score = sum(snap.scores) / len(snap.scores) if snap.scores else 100
        snap.bug_density = (snap.total_findings / max(snap.total_lines, 10)) * 1000
        snap.top_bugs = sorted(bug_kinds.items(), key=lambda x: x[1], reverse=True)[:3]
        snapshots.append(snap)

    # ── 3. 总体统计 ──
    overall_top = sorted(all_bug_kinds.items(), key=lambda x: x[1], reverse=True)[:10]
    all_scores = [s for snap in snapshots for s in snap.scores]
    overall_avg = sum(all_scores) / len(all_scores) if all_scores else 100

    # 趋势判断
    if len(snapshots) >= 2:
        first_half = snapshots[: len(snapshots) // 2]
        second_half = snapshots[len(snapshots) // 2 :]
        first_avg = sum(s.avg_score for s in first_half) / len(first_half)
        second_avg = sum(s.avg_score for s in second_half) / len(second_half)
        if second_avg - first_avg > 3:
            trend = "improving"
        elif first_avg - second_avg > 3:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "stable"

    # ── 4. 向量存储补充（Bug 频率） ──
    if vector_db_path and Path(vector_db_path).exists():
        try:
            conn = sqlite3.connect(vector_db_path)
            rows = conn.execute(
                "SELECT kind, COUNT(*) as cnt FROM patterns GROUP BY kind ORDER BY cnt DESC"
            ).fetchall()
            # 合并到 overall_top_bugs（如果向量库有更多数据）
            for kind, cnt in rows:
                if kind not in dict(overall_top):
                    overall_top.append((kind, cnt))
            overall_top = sorted(overall_top, key=lambda x: x[1], reverse=True)[:10]
            conn.close()
        except Exception:
            pass

    suggestion = _suggestion(overall_top)

    return TrendReport(
        weeks=snapshots,
        overall_top_bugs=overall_top,
        overall_avg_score=round(overall_avg, 1),
        overall_trend=trend,
        suggestion=suggestion,
    )


# ── 格式化输出 ──────────────────────────────────────────────


def fmt_trend_report(report: TrendReport) -> str:
    """将 TrendReport 格式化为 Markdown 周报。"""
    if not report.weeks:
        return "暂无足够数据生成趋势报告。请先使用系统进行多次代码评审。"

    lines = [
        "# [TREND] 代码质量趋势报告",
        "",
        f"> 生成时间：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}",
        f"> 总体平均评分：{report.overall_avg_score:.0f}/100",
        f"> 趋势：{'UP 改善中' if report.overall_trend == 'improving' else 'DOWN 下降中' if report.overall_trend == 'declining' else 'STABLE 稳定'}",
        "",
        "## 评分趋势",
        "",
    ]

    if len(report.weeks) >= 1:
        scores_str = " → ".join(f"{s.avg_score:.0f}" for s in report.weeks)
        labels_str = "  ".join(f"第{i+1}周" for i in range(len(report.weeks)))
        lines.append(f"```")
        lines.append(f"  {scores_str}")
        lines.append(f"  ↑{'  ↑' * (len(report.weeks) - 1)}")
        lines.append(f"  {labels_str}")
        lines.append(f"```")
        lines.append("")

    # Bug 密度趋势
    lines.append("## Bug 密度（每千行）")
    lines.append("")
    if len(report.weeks) >= 1:
        density_str = " → ".join(f"{s.bug_density:.1f}" for s in report.weeks)
        lines.append(f"```")
        lines.append(f"  {density_str}")
        lines.append(f"```")
        lines.append("")

    # 每周明细表
    lines.append("## 每周明细")
    lines.append("")
    lines.append(f"| 周 | 起始 | 评审数 | 代码行 | Findings | 评分 | 密度/千行 | Top Bug |")
    lines.append(f"| --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in report.weeks:
        top = s.top_bugs[0][0] if s.top_bugs else "-"
        lines.append(
            f"| {s.week_label} | {s.week_start} | {s.reviews} | {s.total_lines} | "
            f"{s.total_findings} | {s.avg_score:.0f} | {s.bug_density:.1f} | {top} |"
        )
    lines.append("")

    # Top Bug 类型
    lines.append("## 最常见 Bug 类型 Top 10")
    lines.append("")
    if report.overall_top_bugs:
        for i, (kind, count) in enumerate(report.overall_top_bugs[:10], 1):
            lines.append(f"{i}. **{kind}**（{count} 次）")
    else:
        lines.append("暂无数据")
    lines.append("")

    # 建议
    lines.append("## [FOCUS] 改进建议")
    lines.append("")
    lines.append(report.suggestion)
    lines.append("")

    return "\n".join(lines)


def fmt_trend_json(report: TrendReport) -> str:
    """将 TrendReport 格式化为 JSON。"""
    return json.dumps(
        {
            "overall_avg_score": report.overall_avg_score,
            "overall_trend": report.overall_trend,
            "overall_top_bugs": [
                {"kind": k, "count": c} for k, c in report.overall_top_bugs
            ],
            "suggestion": report.suggestion,
            "weeks": [
                {
                    "week_label": s.week_label,
                    "week_start": s.week_start,
                    "reviews": s.reviews,
                    "total_lines": s.total_lines,
                    "total_findings": s.total_findings,
                    "high_count": s.high_count,
                    "medium_count": s.medium_count,
                    "low_count": s.low_count,
                    "avg_score": round(s.avg_score, 1),
                    "bug_density": round(s.bug_density, 1),
                    "top_bugs": [{"kind": k, "count": c} for k, c in s.top_bugs],
                }
                for s in report.weeks
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


# ── 冒烟测试 ──────────────────────────────────────────────


if __name__ == "__main__":
    import tempfile
    import time as time_mod

    # 模拟多周评审数据
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td)

        # 第1周：质量较差
        for day in range(3):
            ts = datetime(2026, 7, 6 + day, 10, 0, 0, tzinfo=TZ).timestamp()
            report = {
                "risk": "阻止合并",
                "findings": [
                    {"severity": "high", "kind": "mutable_default", "message": "可变默认参数"},
                    {"severity": "medium", "kind": "bare_except", "message": "裸 except"},
                ],
            }
            envelope = {
                "_meta": {"created_at": ts, "code_lines": 80, "key": f"wk1_{day}"},
                "report": report,
            }
            (cache / f"wk1_{day}.json").write_text(
                json.dumps(envelope, ensure_ascii=False), encoding="utf-8"
            )

        # 第2周：质量改善
        for day in range(4):
            ts = datetime(2026, 7, 13 + day, 10, 0, 0, tzinfo=TZ).timestamp()
            findings = (
                [{"severity": "medium", "kind": "long_function", "message": "函数过长"}]
                if day < 2
                else []
            )
            report = {"risk": "修复后合并" if findings else "可合并", "findings": findings}
            envelope = {
                "_meta": {"created_at": ts, "code_lines": 60, "key": f"wk2_{day}"},
                "report": report,
            }
            (cache / f"wk2_{day}.json").write_text(
                json.dumps(envelope, ensure_ascii=False), encoding="utf-8"
            )

        # 分析
        result = analyze(str(cache))
        assert len(result.weeks) == 2, f"expected 2 weeks, got {len(result.weeks)}"
        w1 = result.weeks[0]
        w2 = result.weeks[1]
        assert w1.avg_score < w2.avg_score, f"week1 ({w1.avg_score}) should be < week2 ({w2.avg_score})"
        assert result.overall_trend == "improving"
        print(f"趋势分析 smoke PASS: {len(result.weeks)} 周, 趋势={result.overall_trend}")
        print(f"  W1: 评分={w1.avg_score:.0f}, 密度={w1.bug_density:.1f}, reviews={w1.reviews}")
        print(f"  W2: 评分={w2.avg_score:.0f}, 密度={w2.bug_density:.1f}, reviews={w2.reviews}")
        print(f"  建议: {result.suggestion[:60]}...")

        # 格式化
        md = fmt_trend_report(result)
        assert "[TREND]" in md or "质量趋势" in md
        assert "mutable_default" in md
        print("格式化 smoke PASS")

        js = fmt_trend_json(result)
        data = json.loads(js)
        assert data["overall_trend"] == "improving"
        print("JSON 格式化 smoke PASS")

    # 空数据分析
    with tempfile.TemporaryDirectory() as td:
        result2 = analyze(td)
        assert len(result2.weeks) == 0
        assert "暂无足够数据" in fmt_trend_report(result2)
        print("空数据 smoke PASS")

    print("trend_analyzer 全部 smoke PASS")
