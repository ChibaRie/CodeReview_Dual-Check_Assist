"""三级模型降级链：T1 DeepSeek → T2 Qwen → T3 本地兜底。v0.4 — 按语言隔离。"""
from __future__ import annotations
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import List

from static_check import StaticReport
from circuit_breaker import CircuitBreaker


@dataclass
class ModelConfig:
    name: str
    endpoint: str
    api_key_env: str
    model: str
    timeout: int


@dataclass
class ChainResult:
    """降级链调用结果，记录每条链路的成败。"""

    text: str
    tier: str = ""            # "deepseek" | "qwen" | "local_fallback"
    attempts: list[dict] = field(default_factory=list)  # [{model, success, error?}]


class FallbackChain:
    """三级模型降级链。

    Tier 1: DeepSeek（主模型）
    Tier 2: Qwen（降级模型）
    Tier 3: 本地兜底（永远可用）

    每次失败喂入 per-language 熔断器；熔断器 OPEN 时直接跳到 Tier 3。
    """

    def __init__(self, models: list[ModelConfig], breaker: CircuitBreaker):
        self.models = models
        self.breaker = breaker

    # ── Tier 1 & Tier 2: 远程模型调用 ─────────────────────

    def _call_one(self, model: ModelConfig, prompt: str) -> str:
        key = os.environ.get(model.api_key_env, "")
        if not key:
            raise RuntimeError(f"缺少环境变量 {model.api_key_env}")
        payload = json.dumps(
            {
                "model": model.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 2048,
            }
        ).encode()
        req = urllib.request.Request(
            model.endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=model.timeout) as resp:
            body = json.loads(resp.read().decode())
        return body["choices"][0]["message"]["content"]

    # ── Tier 3: 本地兜底 ──────────────────────────────────

    def _local_fallback(self, static_report: StaticReport, reason: str = "") -> str:
        lines = [
            "## AI 深检暂不可用",
            "",
            f"原因：{reason or '模型链全部失败或熔断器已 OPEN'}。",
            "",
            "基于静态快检结果的最小说明：",
            "",
        ]
        if static_report.findings:
            for f in static_report.findings:
                lines.append(f"- 第 {f.line} 行 [{f.kind}] {f.message}")
        else:
            lines.append("- 未发现静态层可识别的问题。")
        lines += ["", "建议：稍后重试 AI 深检以获得语义层结论。"]
        return "\n".join(lines)

    # ── 三级降级调用 ──────────────────────────────────────

    def call(self, prompt: str, static_report: StaticReport) -> ChainResult:
        """按 T1→T2→T3 顺序尝试，返回 ChainResult。

        熔断器 OPEN 时直接跳到 Tier 3（本地兜底）。
        """
        attempts: list[dict] = []

        # 熔断器闸门检查
        if not self.breaker.allow():
            reason = f"熔断器 {self.breaker.state}（失败 {self.breaker.failures} 次"
            if self.breaker.last_error:
                reason += f"，最后错误: {self.breaker.last_error}"
            reason += "）"
            text = self._local_fallback(static_report, reason)
            return ChainResult(text=text, tier="local_fallback", attempts=attempts)

        # Tier 1 & Tier 2: 遍历远程模型
        tier_names = {0: "deepseek", 1: "qwen"}
        for i, model in enumerate(self.models):
            tier_label = tier_names.get(i, model.name)
            try:
                text = self._call_one(model, prompt)
                self.breaker.record_success()
                attempts.append({"model": model.name, "tier": tier_label, "success": True})
                return ChainResult(text=text, tier=tier_label, attempts=attempts)
            except Exception as exc:
                self.breaker.record_failure(f"{model.name}: {exc}")
                attempts.append(
                    {"model": model.name, "tier": tier_label, "success": False, "error": str(exc)}
                )

        # Tier 3: 本地兜底
        reason = f"全部 {len(self.models)} 个远程模型调用失败"
        text = self._local_fallback(static_report, reason)
        return ChainResult(text=text, tier="local_fallback", attempts=attempts)


# ── 冒烟测试 ──────────────────────────────────────────────

if __name__ == "__main__":
    from static_check import static_check

    # 无模型 → 直接到 Tier 3 本地兜底
    cb = CircuitBreaker(threshold=1, cooldown=60)
    chain = FallbackChain([], cb)
    sr = static_check("x = 1\n", "python")
    result = chain.call("ignored", sr)
    assert "AI 深检暂不可用" in result.text
    assert result.tier == "local_fallback"
    assert cb.state == "CLOSED"  # 无模型不记录失败
    print(f"fallback_chain Tier 3 兜底 smoke PASS (tier={result.tier})")

    # 熔断器 OPEN → 直接跳过远程模型
    cb2 = CircuitBreaker(threshold=1, cooldown=60)
    cb2.record_failure("test")
    assert not cb2.allow()  # OPEN
    chain2 = FallbackChain([], cb2)
    result2 = chain2.call("ignored", sr)
    assert result2.tier == "local_fallback"
    assert "熔断器 OPEN" in result2.text
    print(f"fallback_chain 熔断器 OPEN 跳过 smoke PASS (tier={result2.tier})")

    print("fallback_chain 全部 smoke PASS")
