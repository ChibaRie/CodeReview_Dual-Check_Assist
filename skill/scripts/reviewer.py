"""Reviewer 服务：编排 review() 双检流程。逐字移植自 app.py:165-290。"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

from circuit_breaker import BreakerPool, create_pool
from config import default_config_path, load_config, model_ver, resolve_cache_dir
from cqrs_router import CQRSRouter, make_key
from fallback_chain import ChainResult, FallbackChain, ModelConfig
from state_machine import initial_state, is_terminal, next_state
from static_check import Finding, StaticReport, static_check
from vector_store import PatternMatch, VectorStore

_SOURCE_DELIM = "__AI_DUAL_CHECK_SOURCE__"


class Reviewer:
    def __init__(self) -> None:
        self._breaker_pool: BreakerPool | None = None

    def _prepare(self, config_path: str) -> tuple[dict, str, str, BreakerPool]:
        cfg = (
            load_config(config_path) if config_path and Path(config_path).exists()
            else load_config(default_config_path())
        )
        cache_cfg = cfg.get("cache", {})
        cache_dir = resolve_cache_dir(cache_cfg.get("dir", "data/.cache"), config_path)
        persist_path = str(Path(cache_dir) / ".breaker_state.json")
        if self._breaker_pool is None:
            self._breaker_pool = create_pool(cfg, persist_path)
        return cfg, cache_dir, persist_path, self._breaker_pool

    def _build_prompt(self, static_report: StaticReport, code: str, lang: str, framework: str) -> str:
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

    def _parse_ai(self, text: str) -> AIReport | None:
        from app import AIReport
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

    def _risk(self, ai_report: AIReport | None, static: StaticReport) -> str:
        high = sum(1 for f in static.findings if f.severity == "high")
        if ai_report:
            high += sum(1 for f in ai_report.new_findings if f.severity == "high")
            high += sum(1 for f in ai_report.confirmation if f.severity == "high")
        if high > 0:
            return "阻止合并"
        if static.findings or (ai_report and (ai_report.confirmation or ai_report.new_findings)):
            return "修复后合并"
        return "可合并"

    def merge(self, static_report: StaticReport, ai_report: AIReport | None) -> FinalReport:
        from app import FinalReport
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
        risk = self._risk(ai_report, static_report)
        summary = f"风险等级: {risk}; 静态问题 {len(static_report.findings)} 条"
        if ai_report:
            summary += f"; AI 新发现 {len(ai_report.new_findings)} 条"
        return FinalReport(risk=risk, summary=summary, static_summary=static_report.summary, ai_summary=ai_summary, findings=rows)

    def _read_cache(self, key: str, cache_dir: str, cache_cfg: dict, use_cache: bool
                    ) -> tuple[FinalReport | None, float, CQRSRouter | None]:
        """逐字移植 app.py:204-212。返回 (命中报告|None, cache_lookup_ms, router)。
        router 传出供未命中路径复用（保持旧单一 router 语义）。"""
        from app import FinalReport
        router: CQRSRouter | None = None
        lookup_ms = 0.0
        if use_cache:
            router = CQRSRouter(cache_dir, cache_cfg.get("ttl_days", 7))
            t_cache = time.perf_counter()
            cached = router.try_read(key)
            lookup_ms = (time.perf_counter() - t_cache) * 1000
            if cached:
                return FinalReport(**cached), lookup_ms, router
        return None, lookup_ms, router

    def _get_breaker(self, pool: BreakerPool, lang: str):
        """逐字移植 app.py:217-218。"""
        lang_breaker = pool.get(lang)
        return lang_breaker, lang_breaker.state

    def _run_static(self, code: str, lang: str, review_cfg: dict) -> StaticReport:
        """逐字移植 app.py:221-227。"""
        return static_check(
            code, lang,
            max_function_lines=review_cfg.get("max_function_lines", 50),
            max_nesting=review_cfg.get("max_nesting", 4),
            max_line_length=review_cfg.get("max_line_length", 120),
        )

    def _vector_match(self, static_report: StaticReport, code: str, cache_dir: str
                      ) -> tuple[int, dict | None, VectorStore]:
        """逐字移植 app.py:230-249。返回 (vector_matches, vector_top_match, vstore)。
        vstore 随方法传出——调用方负责 close()（保留旧生命周期）。"""
        vector_db = str(Path(cache_dir) / "patterns.db")
        vstore: VectorStore | None = VectorStore(vector_db)
        vector_matches = 0
        vector_top_match: dict | None = None
        for sf in static_report.findings:
            snippet = "\n".join(code.splitlines()[max(0, sf.line - 2): sf.line + 1])
            matches = vstore.search(kind=sf.kind, snippet=snippet, threshold=0.55, limit=1)
            if matches:
                vector_matches += 1
                if vector_top_match is None or matches[0].combined_sim > (
                    vector_top_match.get("similarity", 0) if vector_top_match else 0
                ):
                    m = matches[0]
                    vector_top_match = {
                        "kind": m.pattern.kind,
                        "message": m.pattern.message,
                        "fix_hint": m.pattern.fix_hint,
                        "similarity": round(m.combined_sim, 2),
                        "source_file": m.pattern.source_file,
                        "days_ago": round((time.time() - m.pattern.created_at) / 86400, 1),
                    }
        return vector_matches, vector_top_match, vstore

    def _run_ai(self, lang_breaker, static_report: StaticReport, code: str, lang: str,
                framework: str, config: dict, pool: BreakerPool, api_key: str = ""
                ) -> tuple[AIReport | None, str, str]:
        """逐字移植 app.py:262-270。返回 (ai_report, ai_tier, new_breaker_state)。
        api_key: 前端传入的显式 key，空串回退到环境变量（向后兼容）。"""
        prompt = self._build_prompt(static_report, code, lang, framework)
        chain = FallbackChain(
            [ModelConfig(**m) for m in config.get("models", [])], lang_breaker
        )
        chain_result: ChainResult = chain.call(prompt, static_report, api_key=api_key)
        ai_tier = chain_result.tier
        new_state = lang_breaker.state
        pool._save()  # 逐字保留私有直调（本轮不清理）
        ai_report = self._parse_ai(chain_result.text)
        return ai_report, ai_tier, new_state

    def _merge_and_store(self, static_report: StaticReport, ai_report: AIReport | None,
                         router: CQRSRouter | None, key: str, code: str, lang: str,
                         cache_hit: bool, vstore: VectorStore
                         ) -> tuple[FinalReport, int]:
        """逐字移植 app.py:271-285。返回 (report, vector_stored)。vstore 由调用方 close()。"""
        report = self.merge(static_report, ai_report)
        if router:
            code_lines = code.count("\n") + 1
            router.write(key, report.__dict__, lang=lang, code_lines=code_lines)
        vector_stored = 0
        if not cache_hit:
            source_file = getattr(static_report, 'source_file', '') or ''  # 逐字保留兜底
            imported = vstore.add_from_report(report.__dict__, code, lang, source_file)
            if imported > 0:
                vector_stored = imported
        return report, vector_stored

    def _done_perf(self, t_total: float, perf: dict) -> dict:
        """收尾 perf['elapsed_ms']（逐字保留旧 app.py:211, 284, 287 计算）。"""
        perf["elapsed_ms"] = (time.perf_counter() - t_total) * 1000
        return perf

    def review(self, code: str, lang: str, framework: str = "",
               config_path: str = "", use_cache: bool = True, api_key: str = ""
               ) -> tuple[FinalReport, dict]:
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

        config, cache_dir, persist_path, pool = self._prepare(config_path)
        cache_cfg = config.get("cache", {})
        mver = model_ver(config.get("models", []))
        key = make_key(code, lang, mver)

        cached, lookup_ms, router = self._read_cache(key, cache_dir, cache_cfg, use_cache)
        perf["cache_lookup_ms"] = lookup_ms
        if cached is not None:
            perf["cache_hit"] = True
            return cached, self._done_perf(t_total, perf)

        lang_breaker, breaker_state = self._get_breaker(pool, lang)
        perf["breaker_state"] = breaker_state

        review_cfg = config.get("review", {})
        static_report = self._run_static(code, lang, review_cfg)

        vm, vtm, vstore = self._vector_match(static_report, code, cache_dir)
        perf["vector_matches"] = vm
        perf["vector_top_match"] = vtm

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
                ai_report, ai_tier, new_state = self._run_ai(
                    lang_breaker, static_report, code, lang, framework, config, pool, api_key
                )
                perf["ai_tier"] = ai_tier
                perf["breaker_state"] = new_state
            if action in ("merge_normal", "merge_degraded"):
                report, vector_stored = self._merge_and_store(
                    static_report, ai_report, router, key, code, lang, perf["cache_hit"], vstore
                )
                perf["vector_stored"] = vector_stored
                if vstore:
                    vstore.close()
                return report, self._done_perf(t_total, perf)

        if vstore:
            vstore.close()
        return self.merge(static_report, None), self._done_perf(t_total, perf)


_default: Reviewer | None = None


def _get_default() -> Reviewer:
    global _default
    if _default is None:
        _default = Reviewer()

    return _default