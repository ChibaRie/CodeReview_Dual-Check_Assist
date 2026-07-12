"""CLI 入口与编排。v0.4 — 按语言隔离的熔断器池。"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from bulkhead import BulkheadExecutor
from circuit_breaker import BreakerPool, CircuitBreaker, create_pool
from cqrs_router import CQRSRouter, make_key
from fallback_chain import ChainResult, FallbackChain, ModelConfig
from health_check import run as health_check_run
from state_machine import initial_state, is_terminal, next_state
from static_check import static_check, Finding, StaticReport
from trend_analyzer import TrendReport, analyze as trend_analyze, fmt_trend_report, fmt_trend_json
from vector_store import PatternMatch, VectorStore
from config import load_config, default_config_path, resolve_cache_dir, model_ver

_SOURCE_DELIM = "__AI_DUAL_CHECK_SOURCE__"

# ── 模块级熔断器池（进程内跨 review() 调用持久） ──────────

_breaker_pool: BreakerPool | None = None


def _get_breaker_pool(config: dict, persist_path: str = "") -> BreakerPool:
    """获取或初始化模块级 BreakerPool。"""
    global _breaker_pool
    if _breaker_pool is None:
        _breaker_pool = create_pool(config, persist_path)
    return _breaker_pool


# ── 数据类 ──────────────────────────────────────────────────


@dataclass
class AIReport:
    confirmation: list[Finding] = field(default_factory=list)
    rejection: list[Finding] = field(default_factory=list)
    new_findings: list[Finding] = field(default_factory=list)


@dataclass
class FinalReport:
    risk: str
    summary: str
    static_summary: str
    ai_summary: str
    findings: list[dict]


# ── 提示词构建 / AI 解析 / 合并 ─────────────────────────────


def _build_prompt(static_report: StaticReport, code: str, lang: str, framework: str) -> str:
    findings_text = "\n".join(f"- 行 {f.line} [{f.kind}] {f.message}" for f in static_report.findings)
    escaped = code.replace(_SOURCE_DELIM, f"{_SOURCE_DELIM}_ESCAPED")
    source_block = f"{_SOURCE_DELIM}\n{escaped}\n{_SOURCE_DELIM}"
    return (
        "你是一位资深代码评审员。请基于以下静态快检结果和源代码，做语义深检。\n\n"
        f"语言: {lang}\n框架: {framework or '无'}\n\n"
        "静态快检发现的问题（可能包含误报）：\n" + (findings_text or "无") + "\n\n"
        "源代码：\n" + source_block + "\n\n"
        "请严格按以下 JSON 格式返回，不要包含任何 markdown 代码块标记：\n"
        '{"confirmation": [{"line": 行号, "kind": "类型", "severity": "high/medium/low", "message": "确认说明"}], '
        '"rejection": [{"line": 行号, "kind": "类型", "severity": "low", "message": "认为是误报的理由"}], '
        '"new_findings": [{"line": 行号, "kind": "类型", "severity": "high/medium/low", "message": "AI 发现静态层漏掉的问题"}]}\n'
    )


def _parse_ai(text: str) -> AIReport | None:
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    raw = m.group(1).strip() if m else text.strip()
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    def to_findings(xs: list[dict]) -> list[Finding]:
        return [
            Finding(x.get("line", 0), x.get("kind", ""), x.get("severity", "low"), x.get("message", ""))
            for x in xs
        ]

    return AIReport(
        confirmation=to_findings(data.get("confirmation", [])),
        rejection=to_findings(data.get("rejection", [])),
        new_findings=to_findings(data.get("new_findings", [])),
    )


def _risk(ai_report: AIReport | None, static: StaticReport) -> str:
    high = sum(1 for f in static.findings if f.severity == "high")
    if ai_report:
        high += sum(1 for f in ai_report.new_findings if f.severity == "high")
        high += sum(1 for f in ai_report.confirmation if f.severity == "high")
    if high > 0:
        return "阻止合并"
    if static.findings or (ai_report and (ai_report.confirmation or ai_report.new_findings)):
        return "修复后合并"
    return "可合并"


def merge(static_report: StaticReport, ai_report: AIReport | None) -> FinalReport:
    rows: list[dict] = [
        {"line": f.line, "layer": "static", "kind": f.kind, "severity": f.severity, "message": f.message}
        for f in static_report.findings
    ]
    if ai_report:
        rows = rows + [
            {"line": f.line, "layer": "ai_confirmed", "kind": f.kind, "severity": f.severity, "message": f.message}
            for f in ai_report.confirmation
        ]
        rows = rows + [
            {"line": f.line, "layer": "ai_new", "kind": f.kind, "severity": f.severity, "message": f.message}
            for f in ai_report.new_findings
        ]
        ai_summary = (
            f"AI 确认 {len(ai_report.confirmation)} 条，新发现 {len(ai_report.new_findings)} 条，"
            f"否定 {len(ai_report.rejection)} 条"
        )
    else:
        ai_summary = "AI 深检未运行（熔断降级或模型链全部失败）"
    risk = _risk(ai_report, static_report)
    summary = f"风险等级: {risk}; 静态问题 {len(static_report.findings)} 条"
    if ai_report:
        summary += f"; AI 新发现 {len(ai_report.new_findings)} 条"
    return FinalReport(risk=risk, summary=summary, static_summary=static_report.summary, ai_summary=ai_summary, findings=rows)


# ── 核心评审流程 ────────────────────────────────────────────


def review(
    code: str,
    lang: str,
    framework: str = "",
    config_path: str = "",
    use_cache: bool = True,
) -> tuple[FinalReport, dict]:
    """执行双检评审，返回 (报告, 性能指标)。

    性能指标包含：
      - cache_hit: bool         是否命中缓存
      - elapsed_ms: float       总耗时（毫秒）
      - cache_lookup_ms: float  缓存查询耗时（毫秒）
      - ai_tier: str            AI 链路（deepseek/qwen/local_fallback/none）
      - breaker_state: str      当前语言的熔断器状态
    """
    perf: dict = {
        "cache_hit": False,
        "elapsed_ms": 0.0,
        "cache_lookup_ms": 0.0,
        "ai_tier": "none",
        "breaker_state": "CLOSED",
        "vector_matches": 0,
        "vector_top_match": None,
        "vector_stored": 0,
    }
    t_total = time.perf_counter()

    config = (
        load_config(config_path) if config_path and Path(config_path).exists()
        else load_config(default_config_path())
    )

    # ── CQRS 缓存（读路径） ──
    cache_cfg = config.get("cache", {})
    cache_dir = resolve_cache_dir(cache_cfg.get("dir", "data/.cache"), config_path)
    mver = model_ver(config.get("models", []))
    key = make_key(code, lang, mver)
    router: CQRSRouter | None = None
    if use_cache:
        router = CQRSRouter(cache_dir, cache_cfg.get("ttl_days", 7))
        t_cache = time.perf_counter()
        cached = router.try_read(key)
        perf["cache_lookup_ms"] = (time.perf_counter() - t_cache) * 1000
        if cached:
            perf["cache_hit"] = True
            perf["elapsed_ms"] = (time.perf_counter() - t_total) * 1000
            return FinalReport(**cached), perf

    # ── 获取 per-language 熔断器（始终持久化，不受 --no-cache 影响） ──
    persist_path = str(Path(cache_dir) / ".breaker_state.json")
    pool = _get_breaker_pool(config, persist_path)
    lang_breaker = pool.get(lang)
    perf["breaker_state"] = lang_breaker.state

    # ── 静态快检 ──
    review_cfg = config.get("review", {})
    static_report = static_check(
        code, lang,
        max_function_lines=review_cfg.get("max_function_lines", 50),
        max_nesting=review_cfg.get("max_nesting", 4),
        max_line_length=review_cfg.get("max_line_length", 120),
    )

    # ── 向量记忆：搜索历史相似 Bug 模式（独立于缓存，始终启用） ──
    vector_db = str(Path(cache_dir) / "patterns.db")
    vstore: VectorStore | None = VectorStore(vector_db)
    # 对每个静态 finding 搜索历史相似模式
    for sf in static_report.findings:
        snippet = "\n".join(code.splitlines()[max(0, sf.line - 2): sf.line + 1])
        matches = vstore.search(kind=sf.kind, snippet=snippet, threshold=0.55, limit=1)
        if matches:
            perf["vector_matches"] += 1
            if perf["vector_top_match"] is None or matches[0].combined_sim > (
                perf["vector_top_match"].get("similarity", 0) if perf["vector_top_match"] else 0
            ):
                m = matches[0]
                perf["vector_top_match"] = {
                    "kind": m.pattern.kind,
                    "message": m.pattern.message,
                    "fix_hint": m.pattern.fix_hint,
                    "similarity": round(m.combined_sim, 2),
                    "source_file": m.pattern.source_file,
                    "days_ago": round((time.time() - m.pattern.created_at) / 86400, 1),
                }

    # ── 状态机 + AI 降级链 ──
    state = initial_state()
    ai_report: AIReport | None = None
    while not is_terminal(state):
        state, action = next_state(state, "")
        if action == "run_static":
            continue
        if action == "check_gate":
            event = "allowed" if lang_breaker.allow() else "blocked"
            state, action = next_state(state, event)
        if action == "run_ai":
            prompt = _build_prompt(static_report, code, lang, framework)
            chain = FallbackChain(
                [ModelConfig(**m) for m in config.get("models", [])], lang_breaker
            )
            chain_result: ChainResult = chain.call(prompt, static_report)
            perf["ai_tier"] = chain_result.tier
            perf["breaker_state"] = lang_breaker.state  # 更新（可能因调用而改变）
            pool._save()  # 持久化熔断器状态
            ai_report = _parse_ai(chain_result.text)
        if action in ("merge_normal", "merge_degraded"):
            report = merge(static_report, ai_report)
            if router:
                code_lines = code.count("\n") + 1
                router.write(key, report.__dict__, lang=lang, code_lines=code_lines)
            # ── 向量记忆：存储新 findings 到模式库 ──
            if not perf["cache_hit"]:
                source_file = getattr(static_report, 'source_file', '') or ''
                imported = vstore.add_from_report(report.__dict__, code, lang, source_file)
                if imported > 0:
                    perf["vector_stored"] = imported
            if vstore:
                vstore.close()
            perf["elapsed_ms"] = (time.perf_counter() - t_total) * 1000
            return report, perf

    perf["elapsed_ms"] = (time.perf_counter() - t_total) * 1000
    if vstore:
        vstore.close()
    return merge(static_report, None), perf


# ── 格式化输出 ──────────────────────────────────────────────


def _fmt(report: FinalReport) -> str:
    header = [
        "# 双检代码评审报告", "",
        f"风险等级: {report.risk}", "",
        "## 摘要", report.summary, "",
        "## 静态层", report.static_summary, "",
        "## AI 层", report.ai_summary, "",
        "## 明细",
    ]
    detail = [
        f'- 行 {f["line"]} [{f["layer"]}:{f["kind"]}] {f["severity"]} — {f["message"]}'
        for f in report.findings
    ]
    return "\n".join(header + detail)


def _fmt_perf(perf: dict) -> str:
    """格式化性能/熔断器状态摘要。"""
    lines = []
    if perf["cache_hit"]:
        lines.append(
            f"[CACHE HIT] 响应耗时 {perf['elapsed_ms']:.0f} ms（查询 {perf['cache_lookup_ms']:.1f} ms）"
        )
    else:
        lines.append(f"[CACHE MISS] 完整评审耗时 {perf['elapsed_ms']:.0f} ms")
    if perf.get("ai_tier") and perf["ai_tier"] != "none":
        tier_names = {"deepseek": "T1·DeepSeek", "qwen": "T2·Qwen", "local_fallback": "T3·本地兜底"}
        tier_label = tier_names.get(perf["ai_tier"], perf["ai_tier"])
        lines.append(f"[AI 链路] {tier_label}")
    bs = perf.get("breaker_state", "CLOSED")
    if bs != "CLOSED":
        lines.append(f"[熔断器] {bs}")
    vm = perf.get("vector_matches", 0)
    if vm > 0:
        lines.append(f"[向量记忆] 匹配 {vm} 条历史相似模式")
        top = perf.get("vector_top_match")
        if top:
            lines.append(f"  -> [{top['kind']}] 相似度 {top['similarity']:.0%}，{top['days_ago']:.0f} 天前")
            if top.get("fix_hint"):
                lines.append(f"  -> 历史修复: {top['fix_hint'][:80]}")
    vs = perf.get("vector_stored", 0)
    if vs:
        lines.append(f"[向量记忆] 新存储 {vs} 条模式")
    return "\n".join(lines)


# ── 批量评审（舱壁隔离） ─────────────────────────────────────


def _run_batch(
    directory: Path,
    lang: str = "python",
    framework: str = "",
    config_path: str = "",
    use_cache: bool = True,
    line_threshold: int = 500,
    json_out: bool = False,
) -> None:
    """批量评审目录下所有代码文件，通过舱壁隔离执行。

    小文件（≤500行）→ normal pool（10 并发），快速返回。
    大文件（>500行）→ large pool（2 并发），不阻塞小文件。
    """
    import time as time_mod

    _LANG_MAP = {".py": "python", ".go": "go", ".js": "javascript", ".ts": "javascript"}

    files = sorted(
        [f for f in directory.iterdir() if f.is_file() and f.suffix in _LANG_MAP]
    )
    if not files:
        print(f"目录 {directory} 中没有找到代码文件（.py/.go/.js）")
        return

    print(f"舱壁批量评审：{len(files)} 个文件（阈值 {line_threshold} 行）")
    print(f"  normal pool: 10 workers（≤{line_threshold}行）")
    print(f"  large pool:   2 workers（>{line_threshold}行）")
    lang = lang or "python"
    print(f"  语言: {lang}（自动检测扩展名覆盖）")
    print(f"{'='*70}")

    # 分类（自动检测语言）
    small_files, large_files = [], []
    for f in files:
        try:
            code = f.read_text(encoding="utf-8")
            lines = code.count("\n") + 1
            file_lang = _LANG_MAP.get(f.suffix, lang)
            if lines > line_threshold:
                large_files.append((f, code, lines, file_lang))
            else:
                small_files.append((f, code, lines, file_lang))
        except Exception as exc:
            print(f"  [SKIP] {f.name}: 读取失败 ({exc})")

    print(f"\n  小文件: {len(small_files)} 个（normal pool）")
    print(f"  大文件: {len(large_files)} 个（large pool）")
    print()

    # 使用舱壁执行器
    with BulkheadExecutor(line_threshold=line_threshold) as bh:
        t_start = time_mod.perf_counter()

        # 提交所有文件（使用各自检测到的语言）
        all_files = small_files + large_files
        for f, code, lines, file_lang in all_files:
            bh.submit(review, code, file_lang, framework=framework, config_path=config_path, use_cache=use_cache)

        # 收集结果
        results: list[tuple[str, float, dict]] = []  # (risk, ms, perf)
        for future in bh._futures:
            try:
                report, perf = future.result()
                results.append((report.risk, perf["elapsed_ms"], perf))
            except Exception as exc:
                results.append((f"ERROR: {exc}", 0, {}))

        # 与文件关联
        final = []
        for (f, code, lines, file_lang), (risk, ms, perf) in zip(all_files, results):
            final.append((f.name, lines, risk, ms, perf))

        total_ms = (time_mod.perf_counter() - t_start) * 1000

        # 输出结果
        if json_out:
            out = {
                "batch_summary": {
                    "total_files": len(final),
                    "total_ms": round(total_ms, 1),
                    "small_files": len(small_files),
                    "large_files": len(large_files),
                },
                "bulkhead_stats": bh.stats(),
                "files": [
                    {
                        "file": name,
                        "lines": lines,
                        "risk": risk,
                        "elapsed_ms": round(ms, 1),
                        "pool": "large" if lines > line_threshold else "normal",
                        "perf": perf,
                    }
                    for name, lines, risk, ms, perf in final
                ],
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            # 表格输出
            pool_width = 8
            print(f"{'文件':<35} {'行数':<8} {'池':<{pool_width}} {'耗时':<10} {'风险等级'}")
            print("-" * 90)
            for name, lines, risk, ms, perf in final:
                pool_label = "large" if lines > line_threshold else "normal"
                print(f"{name:<35} {lines:<8} {pool_label:<{pool_width}} {ms:>6.0f} ms   {risk}")

            print(f"\n{'='*70}")
            print(f"总耗时: {total_ms:.0f} ms（{len(final)} 个文件）")

            stats = bh.stats()
            np_s = stats["normal_pool"]
            lp_s = stats["large_pool"]
            print(f"normal pool: {np_s['completed']} 完成, 平均 {np_s['avg_wait_ms']:.0f} ms/文件")
            print(f"large pool:  {lp_s['completed']} 完成, 平均 {lp_s['avg_wait_ms']:.0f} ms/文件")
            if np_s["avg_wait_ms"] > 0 and lp_s["avg_wait_ms"] > 0:
                ratio = lp_s["avg_wait_ms"] / max(np_s["avg_wait_ms"], 0.1)
                print(f"大/小文件耗时比: {ratio:.1f}x")

            # 关键指标
            if small_files and large_files:
                small_times = [ms for name, lines, risk, ms, perf in final if lines <= line_threshold]
                large_times = [ms for name, lines, risk, ms, perf in final if lines > line_threshold]
                if small_times:
                    avg_small = sum(small_times) / len(small_times)
                    avg_large = sum(large_times) / len(large_times) if large_times else 0
                    print(f"\n舱壁隔离效果:")
                    print(f"  小文件平均耗时: {avg_small:.0f} ms（目标 < 3s）")
                    print(f"  大文件平均耗时: {avg_large:.0f} ms")
                    if avg_small < 3000:
                        print(f"  [PASS] 小文件不受大文件阻塞")


# ── 冒烟 ────────────────────────────────────────────────────


def _smoke() -> None:
    bad = "def f(a=[]):\n    try:\n        x = 1\n    except:\n        pass\n"
    r, perf = review(bad, "python")
    assert r.risk in ("修复后合并", "阻止合并"), r.risk
    print(f"app smoke PASS: {r.summary} ({perf['elapsed_ms']:.0f} ms)")


# ── CLI ─────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 代码评审双检助手")
    parser.add_argument("code", nargs="?", help="代码文件路径；为空时读标准输入")
    parser.add_argument("--code-string", dest="code_string", help="直接传入代码字符串")
    parser.add_argument("--lang", help="语言，如 python / go / javascript")
    parser.add_argument("--framework", default="", help="框架/库上下文")
    parser.add_argument("--config", default="", help="配置文件路径")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--health", action="store_true", help="系统健康度自检")
    parser.add_argument("--breaker-status", action="store_true", help="查看所有语言熔断器状态")
    parser.add_argument("--breaker-reset", nargs="?", const="", help="重置熔断器（可指定语言）")
    parser.add_argument("--batch", help="批量评审目录下所有文件（舱壁隔离模式）")
    parser.add_argument("--batch-lang", default="python", help="批量模式的语言（默认 python）")
    parser.add_argument("--bulkhead-threshold", type=int, default=500, help="舱壁行数阈值（默认 500）")
    parser.add_argument("--vector-stats", action="store_true", help="查看向量记忆统计")
    parser.add_argument("--vector-import", help="从已有评审 JSON 文件导入模式到向量存储")
    parser.add_argument("--trend-report", action="store_true", help="生成代码质量趋势报告")
    parser.add_argument("--trend-weeks", type=int, default=8, help="趋势报告回溯周数（默认 8）")
    args = parser.parse_args()

    # ── 熔断器管理命令 ──
    if args.breaker_reset is not None:
        config = load_config(args.config) if args.config and Path(args.config).exists() else load_config(default_config_path())
        cache_dir = resolve_cache_dir(
            config.get("cache", {}).get("dir", "data/.cache"), args.config if args.config else ""
        )
        persist_path = str(Path(cache_dir) / ".breaker_state.json")
        pool = _get_breaker_pool(config, persist_path)
        target = args.breaker_reset if args.breaker_reset else ""
        pool.reset(target)
        if target:
            print(f"熔断器 [{target}] 已重置为 CLOSED")
        else:
            print("全部熔断器已重置为 CLOSED")
        pool._save()
        return

    if args.breaker_status:
        config = load_config(args.config) if args.config and Path(args.config).exists() else load_config(default_config_path())
        cache_dir = resolve_cache_dir(
            config.get("cache", {}).get("dir", "data/.cache"), args.config if args.config else ""
        )
        persist_path = str(Path(cache_dir) / ".breaker_state.json")
        pool = _get_breaker_pool(config, persist_path)
        status = pool.status()
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            if not status:
                print("无熔断器记录（尚未评审任何代码）")
                return
            print(f"{'语言':<12} {'状态':<12} {'失败':<6} {'阈值':<6} {'冷却(s)':<10} {'最后错误'}")
            print("-" * 80)
            for lang, s in sorted(status.items()):
                err = s.get("last_error", "")[:40]
                print(f"{lang:<12} {s['state']:<12} {s['failures']:<6} {s['threshold']:<6} {s['cooldown']:<10} {err}")
        return

    # ── 健康度自检 ──
    if args.health:
        sp = str(Path(__file__).resolve().parents[2] / "system" / "status.md")
        cd = resolve_cache_dir("data/.cache", args.config if args.config else "")
        status = health_check_run(cd, sp)
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            h = status["health"]
            c = status["cache"]
            hit_rate = 0.0
            if c.get("total_access", 0) > 0:
                hit_rate = c.get("hits", 0) / c["total_access"]
            print(f"缓存: {h['cache']} ({c['files']} 文件, {c['total_size_kb']} KB)")
            print(f"CQRS 统计: 命中 {c.get('hits', 0)} / 共 {c.get('total_access', 0)} 次 (命中率 {hit_rate:.0%})")
            print(f"规则: {h['rules']} ({status['rules']['count']} 个文件)")
            if status.get("breaker"):
                print(f"熔断器: {status['breaker']}")
            print(f"整体: {h['overall']}")
            print(f"状态文件: {sp}")
        return

    # ── 趋势报告 ──
    if args.trend_report:
        cache_dir = resolve_cache_dir("data/.cache", args.config if args.config else "")
        vdb = str(Path(cache_dir) / "patterns.db")
        report: TrendReport = trend_analyze(cache_dir, vdb)
        if args.json:
            print(fmt_trend_json(report))
        else:
            print(fmt_trend_report(report))
        return

    # ── 向量记忆管理命令 ──
    if args.vector_import:
        vdb = str(Path(resolve_cache_dir("data/.cache", args.config if args.config else "")) / "patterns.db")
        vstore = VectorStore(vdb)
        imported_count = 0
        import_path = Path(args.vector_import)
        if import_path.is_file():
            try:
                data = json.loads(import_path.read_text(encoding="utf-8"))
                code = data.get("_source_code", "")
                lang = data.get("_lang", "python")
                source = import_path.name
                imported_count = vstore.add_from_report(data, code, lang, source)
            except Exception as exc:
                print(f"导入失败: {exc}")
                vstore.close()
                sys.exit(1)
        else:
            print(f"错误：{args.vector_import} 不是有效文件")
            vstore.close()
            sys.exit(1)
        print(f"从 {import_path.name} 导入 {imported_count} 条新模式")
        s = vstore.stats()
        print(f"向量存储总计: {s['total_patterns']} 条模式")
        vstore.close()
        return

    if args.vector_stats:
        vdb = str(Path(resolve_cache_dir("data/.cache", args.config if args.config else "")) / "patterns.db")
        vstore = VectorStore(vdb)
        s = vstore.stats()
        if args.json:
            print(json.dumps(s, ensure_ascii=False, indent=2))
        else:
            print(f"向量记忆统计:")
            print(f"  数据库: {s['db_path']}")
            print(f"  总模式数: {s['total_patterns']}")
            if s["top_kinds"]:
                print(f"\n  Top Bug 类型:")
                for k in s["top_kinds"]:
                    print(f"    {k['kind']:<25} {k['count']} 条")
            if s["by_language"]:
                print(f"\n  按语言分布:")
                for l in s["by_language"]:
                    print(f"    {l['lang']:<15} {l['count']} 条")
        vstore.close()
        return

    # ── 批量评审模式（舱壁隔离） ──
    if args.batch:
        batch_dir = Path(args.batch)
        if not batch_dir.is_dir():
            print(f"错误：{args.batch} 不是有效目录")
            sys.exit(1)
        _run_batch(
            batch_dir,
            lang=args.batch_lang,
            framework=args.framework,
            config_path=args.config,
            use_cache=not args.no_cache,
            line_threshold=args.bulkhead_threshold,
            json_out=args.json,
        )
        return

    # ── 冒烟测试（无参数时） ──
    if not args.lang and not args.code and not args.code_string:
        _smoke()
        return

    if not args.lang:
        parser.error("--lang 是必填参数")

    if args.code_string:
        src = args.code_string
    elif args.code:
        src = Path(args.code).read_text(encoding="utf-8")
    else:
        src = sys.stdin.read()

    report, perf = review(src, args.lang, args.framework, args.config, use_cache=not args.no_cache)

    if args.json:
        out = report.__dict__
        out["_perf"] = perf
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(_fmt(report))
        print()
        print(_fmt_perf(perf))


if __name__ == "__main__":
    main()
