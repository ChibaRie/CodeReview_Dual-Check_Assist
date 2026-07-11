"""模型降级链：DeepSeek -> Qwen -> 本地兜底。"""
from __future__ import annotations
import json
import os
import urllib.request
from dataclasses import dataclass
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


class FallbackChain:
    def __init__(self, models: List[ModelConfig], breaker: CircuitBreaker):
        self.models = models
        self.breaker = breaker

    def _call_one(self, model: ModelConfig, prompt: str) -> str:
        key = os.environ.get(model.api_key_env, "")
        if not key:
            raise RuntimeError(f"缺少环境变量 {model.api_key_env}")
        payload = json.dumps({
            "model": model.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 2048
        }).encode()
        req = urllib.request.Request(
            model.endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=model.timeout) as resp:
            body = json.loads(resp.read().decode())
        return body["choices"][0]["message"]["content"]

    def _local_fallback(self, static_report: StaticReport) -> str:
        lines = ["## AI 深检暂不可用", "", "原因：模型链全部失败或熔断器已 OPEN。",
                 "", "基于静态快检结果的最小说明：", ""]
        if static_report.findings:
            for f in static_report.findings:
                lines.append(f"- 第 {f.line} 行 [{f.kind}] {f.message}")
        else:
            lines.append("- 未发现静态层可识别的问题。")
        lines += ["", "建议：稍后重试 AI 深检以获得语义层结论。"]
        return "\n".join(lines)

    def call(self, prompt: str, static_report: StaticReport) -> str:
        for model in self.models:
            try:
                text = self._call_one(model, prompt)
                self.breaker.record_success()
                return text
            except Exception:
                self.breaker.record_failure()
        return self._local_fallback(static_report)


if __name__ == "__main__":
    from static_check import static_check
    cb = CircuitBreaker(threshold=1, cooldown=60)
    chain = FallbackChain([], cb)
    sr = static_check("x = 1\n", "python")
    out = chain.call("ignored", sr)
    assert "AI 深检暂不可用" in out
    assert cb.state == "CLOSED"   # no models, no failure recorded
    print("fallback_chain fallback smoke PASS")
