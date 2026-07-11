"""CLI 入口与编排。"""
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from circuit_breaker import CircuitBreaker
from cqrs_router import CQRSRouter, make_key
from fallback_chain import FallbackChain, ModelConfig
from state_machine import initial_state, is_terminal, next_state
from static_check import static_check, Finding, StaticReport


@dataclass
class AIReport:
    confirmation: List[Finding] = field(default_factory=list)
    rejection: List[Finding] = field(default_factory=list)
    new_findings: List[Finding] = field(default_factory=list)


@dataclass
class FinalReport:
    risk: str
    summary: str
    static_summary: str
    ai_summary: str
    findings: List[dict]


def _load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _default_config_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "references" / "config.example.json")


def _model_ver(models: List[dict]) -> str:
    return json.dumps(models, sort_keys=True)[:32]


def _build_prompt(static_report: StaticReport, code: str, lang: str, framework: str) -> str:
    findings_text = "\n".join(f"- 行 {f.line} [{f.kind}] {f.message}" for f in static_report.findings)
    return (
        "你是一位资深代码评审员。请基于以下静态快检结果和源代码，做语义深检。\n\n"
        f"语言: {lang}\n框架: {framework or '无'}\n\n"
        "静态快检发现的问题（可能包含误报）：\n" + (findings_text or "无") + "\n\n"
        "源代码：\n```\n" + code + "```\n\n"
        "请严格按以下 JSON 格式返回，不要包含任何 markdown 代码块标记：\n"
        '{"confirmation": [{"line": 行号, "kind": "类型", "severity": "high/medium/low", "message": "确认说明"}], '
        '"rejection": [{"line": 行号, "kind": "类型", "severity": "low", "message": "认为是误报的理由"}], '
        '"new_findings": [{"line": 行号, "kind": "类型", "severity": "high/medium/low", "message": "AI 发现静态层漏掉的问题"}]}\n'
    )


def _parse_ai(text: str) -> Optional[AIReport]:
    try:
        data = json.loads(text.strip())
    except Exception:
        return None
    def to_findings(xs):
        return [Finding(x.get("line", 0), x.get("kind", ""), x.get("severity", "low"),
                        x.get("message", "")) for x in xs]
    return AIReport(
        confirmation=to_findings(data.get("confirmation", [])),
        rejection=to_findings(data.get("rejection", [])),
        new_findings=to_findings(data.get("new_findings", []))
    )


def _risk(ai_report: Optional[AIReport], static: StaticReport) -> str:
    high = sum(1 for f in static.findings if f.severity == "high")
    if ai_report:
        high += sum(1 for f in ai_report.new_findings if f.severity == "high")
        high += sum(1 for f in ai_report.confirmation if f.severity == "high")
    if high > 0:
        return "阻止合并"
    if static.findings or (ai_report and (ai_report.confirmation or ai_report.new_findings)):
        return "修复后合并"
    return "可合并"


def merge(static_report: StaticReport, ai_report: Optional[AIReport], ai_text: str) -> FinalReport:
    rows: List[dict] = []
    # 静态确认（无论 AI 是否参与都列出）
    for f in static_report.findings:
        rows.append({"line": f.line, "layer": "static", "kind": f.kind,
                     "severity": f.severity, "message": f.message})
    if ai_report:
        for f in ai_report.confirmation:
            rows.append({"line": f.line, "layer": "ai_confirmed", "kind": f.kind,
                         "severity": f.severity, "message": f.message})
        for f in ai_report.new_findings:
            rows.append({"line": f.line, "layer": "ai_new", "kind": f.kind,
                         "severity": f.severity, "message": f.message})
        ai_summary = f"AI 确认 {len(ai_report.confirmation)} 条，新发现 {len(ai_report.new_findings)} 条，否定 {len(ai_report.rejection)} 条"
    else:
        ai_summary = "AI 深检未运行（熔断降级或模型链全部失败）"
    risk = _risk(ai_report, static_report)
    summary = f"风险等级: {risk}; 静态问题 {len(static_report.findings)} 条"
    if ai_report:
        summary += f"; AI 新发现 {len(ai_report.new_findings)} 条"
    return FinalReport(risk=risk, summary=summary, static_summary=static_report.summary,
                       ai_summary=ai_summary, findings=rows)


def review(code: str, lang: str, framework: str = "", config_path: str = "") -> FinalReport:
    config = _load_config(config_path) if config_path and Path(config_path).exists() else _load_config(
        _default_config_path())
    cache_cfg = config.get("cache", {})
    router = CQRSRouter(cache_cfg.get("dir", "data/.cache"), cache_cfg.get("ttl_days", 7))
    mver = _model_ver(config.get("models", []))
    key = make_key(code, lang, mver)
    cached = router.try_read(key)
    if cached:
        return FinalReport(**cached)

    breaker_cfg = config.get("breaker", {})
    breaker = CircuitBreaker(breaker_cfg.get("threshold", 3), breaker_cfg.get("cooldown", 60))
    review_cfg = config.get("review", {})
    static_report = static_check(code, lang,
                                  max_function_lines=review_cfg.get("max_function_lines", 50),
                                  max_nesting=review_cfg.get("max_nesting", 4))

    state = initial_state()
    ai_report: Optional[AIReport] = None
    ai_text = ""
    while not is_terminal(state):
        state, action = next_state(state, "")
        if action == "run_static":
            continue
        if action == "check_gate":
            event = "allowed" if breaker.allow() else "blocked"
            state, action = next_state(state, event)
        if action == "run_ai":
            prompt = _build_prompt(static_report, code, lang, framework)
            chain = FallbackChain([ModelConfig(**m) for m in config.get("models", [])], breaker)
            ai_text = chain.call(prompt, static_report)
            ai_report = _parse_ai(ai_text)
            if ai_report is None and "AI 深检暂不可用" not in ai_text:
                # 模型返回了非 JSON，视为模型失败
                breaker.record_failure()
                ai_text = chain.call(prompt, static_report)
                ai_report = _parse_ai(ai_text)
        # merge_normal or merge_degraded
        report = merge(static_report, ai_report, ai_text)
        router.write(key, report.__dict__)
        return report
    return merge(static_report, None, "")


def _fmt(report: FinalReport) -> str:
    lines = ["# 双检代码评审报告", "", f"风险等级: {report.risk}", "", "## 摘要", report.summary,
             "", "## 静态层", report.static_summary, "", "## AI 层", report.ai_summary, "", "## 明细"]
    for f in report.findings:
        lines.append(f'- 行 {f["line"]} [{f["layer"]}:{f["kind"]}] {f["severity"]} — {f["message"]}')
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 代码评审双检助手")
    parser.add_argument("code", nargs="?", help="代码文件路径；为空时读标准输入")
    parser.add_argument("--code-string", dest="code_string", help="直接传入代码字符串")
    parser.add_argument("--lang", required=True, help="语言，如 python / go / javascript")
    parser.add_argument("--framework", default="", help="框架/库上下文")
    parser.add_argument("--config", default="", help="配置文件路径")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if args.code_string:
        src = args.code_string
    elif args.code:
        src = Path(args.code).read_text(encoding="utf-8")
    else:
        src = sys.stdin.read()

    report = review(src, args.lang, args.framework, args.config)
    if args.json:
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
    else:
        print(_fmt(report))


if __name__ == "__main__":
    # Smoke: 用坏代码跑一次，验证双检出报告
    bad = '''def f(a=[]):
    try:
        x = 1
    except:
        pass
'''
    r = review(bad, "python")
    assert r.risk in ("修复后合并", "阻止合并"), r.risk
    print("app smoke PASS:", r.summary)
