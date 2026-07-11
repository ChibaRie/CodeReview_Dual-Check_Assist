"""熔断器 + BreakerPool：AI 子系统健康闸门。v0.4 — 按语言隔离 + 文件持久化。"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── 单熔断器 ──────────────────────────────────────────────


@dataclass
class CircuitBreaker:
    """三态熔断器：CLOSED → OPEN → HALF_OPEN → CLOSED。

    CLOSED:     正常放行，累计失败达 threshold → OPEN
    OPEN:       拒绝放行，cooldown 秒后 → HALF_OPEN
    HALF_OPEN:  允许一次探针，成功 → CLOSED，失败 → OPEN
    """

    threshold: int = 3
    cooldown: float = 60.0
    state: str = field(default="CLOSED")
    failures: int = field(default=0)
    opened_at: float = field(default=0.0)
    last_error: str = field(default="")

    def allow(self) -> bool:
        now = time.time()
        if self.state == "OPEN":
            if now - self.opened_at >= self.cooldown:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        if self.state == "HALF_OPEN":
            self.failures = 0
            self.state = "CLOSED"
            self.last_error = ""
        elif self.state == "CLOSED":
            self.failures = 0

    def record_failure(self, reason: str = "") -> None:
        self.failures += 1
        self.last_error = reason or self.last_error
        if self.failures >= self.threshold:
            self.state = "OPEN"
            self.opened_at = time.time()

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "failures": self.failures,
            "opened_at": self.opened_at,
            "threshold": self.threshold,
            "cooldown": self.cooldown,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CircuitBreaker":
        return cls(
            threshold=d.get("threshold", 3),
            cooldown=d.get("cooldown", 60.0),
            state=d.get("state", "CLOSED"),
            failures=d.get("failures", 0),
            opened_at=d.get("opened_at", 0.0),
            last_error=d.get("last_error", ""),
        )


# ── 按语言隔离的熔断器池 ──────────────────────────────────


@dataclass
class BreakerPool:
    """按语言隔离的熔断器池。

    cb_pool = {
        "python": CircuitBreaker(threshold=3, cooldown=30),  # Python 熔断了
        "go":     CircuitBreaker(threshold=3, cooldown=30),  # Go 不受影响
        "java":   CircuitBreaker(threshold=5, cooldown=60),  # Java 阈值更宽松
        "rust":   CircuitBreaker(threshold=3, cooldown=30),
    }

    每个语言的熔断器独立计数和状态切换，一个语言熔断不影响其他语言。
    """

    _pool: dict[str, CircuitBreaker] = field(default_factory=dict)
    _configs: dict[str, dict] = field(default_factory=dict)
    _default_config: dict = field(default_factory=lambda: {"threshold": 3, "cooldown": 60.0})
    _persist_path: str = ""

    def __post_init__(self):
        if self._persist_path:
            self._load()

    # ── 注册语言配置 ──────────────────────────────────────

    def register(self, lang: str, threshold: int = 3, cooldown: float = 60.0) -> None:
        """注册一个语言的熔断器配置（如果尚未在池中）。"""
        self._configs[lang] = {"threshold": threshold, "cooldown": cooldown}
        if lang not in self._pool:
            self._pool[lang] = CircuitBreaker(threshold=threshold, cooldown=cooldown)
            self._save()

    def record_failure(self, lang: str, reason: str = "") -> None:
        """记录指定语言的失败并持久化。"""
        self.get(lang).record_failure(reason)
        self._save()

    def record_success(self, lang: str) -> None:
        """记录指定语言的成功并持久化。"""
        self.get(lang).record_success()
        self._save()

    def get(self, lang: str) -> CircuitBreaker:
        """获取指定语言的熔断器。未注册语言使用默认配置。"""
        if lang in self._pool:
            return self._pool[lang]
        cfg = self._configs.get(lang, self._default_config)
        cb = CircuitBreaker(threshold=cfg.get("threshold", 3), cooldown=cfg.get("cooldown", 60.0))
        self._pool[lang] = cb
        self._save()
        return cb

    # ── 批量操作 ──────────────────────────────────────────

    def status(self) -> dict:
        """返回所有语言熔断器的当前状态摘要。"""
        return {
            lang: cb.to_dict()
            for lang, cb in self._pool.items()
        }

    def any_open(self) -> list[str]:
        """返回当前处于 OPEN 状态的语言列表。"""
        return [lang for lang, cb in self._pool.items() if cb.state == "OPEN"]

    def reset(self, lang: str = "") -> None:
        """重置指定语言或全部语言的熔断器到 CLOSED 状态。"""
        if lang:
            if lang in self._pool:
                self._pool[lang] = CircuitBreaker(
                    threshold=self._pool[lang].threshold,
                    cooldown=self._pool[lang].cooldown,
                )
        else:
            for l in list(self._pool.keys()):
                cb = self._pool[l]
                self._pool[l] = CircuitBreaker(threshold=cb.threshold, cooldown=cb.cooldown)
        self._save()

    # ── 文件持久化 ────────────────────────────────────────

    def _persist_file(self) -> Path | None:
        if not self._persist_path:
            return None
        p = Path(self._persist_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _save(self) -> None:
        pf = self._persist_file()
        if not pf:
            return
        data = {lang: cb.to_dict() for lang, cb in self._pool.items()}
        pf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        pf = self._persist_file()
        if not pf or not pf.exists():
            return
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
            for lang, d in data.items():
                cb = CircuitBreaker.from_dict(d)
                if lang in self._configs:
                    cb.threshold = self._configs[lang].get("threshold", cb.threshold)
                    cb.cooldown = self._configs[lang].get("cooldown", cb.cooldown)
                self._pool[lang] = cb
        except Exception:
            pass


# ── 工厂函数 ──────────────────────────────────────────────


def create_pool(config: dict, persist_path: str = "") -> BreakerPool:
    """从配置字典创建 BreakerPool。

    config 格式：
    {
        "breaker": {
            "default": {"threshold": 3, "cooldown": 60},
            "per_language": {
                "python": {"threshold": 3, "cooldown": 30},
                "go":     {"threshold": 3, "cooldown": 30},
                "java":   {"threshold": 5, "cooldown": 60},
                "rust":   {"threshold": 3, "cooldown": 30}
            }
        }
    }
    """
    breaker_cfg = config.get("breaker", {})
    default_cfg = breaker_cfg.get("default", {"threshold": 3, "cooldown": 60})
    per_lang = breaker_cfg.get("per_language", {})

    pool = BreakerPool(
        _default_config=default_cfg,
        _configs=per_lang,
        _persist_path=persist_path,
    )
    # 预注册所有配置了 per_language 的语言
    for lang, cfg in per_lang.items():
        pool.register(lang, threshold=cfg.get("threshold", 3), cooldown=cfg.get("cooldown", 60))
    return pool


# ── 冒烟测试 ──────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    # 单熔断器三态
    cb = CircuitBreaker(threshold=2, cooldown=0.1)
    assert cb.allow()
    cb.record_failure("timeout")
    cb.record_failure("timeout")
    assert not cb.allow()
    assert cb.state == "OPEN"
    time.sleep(0.15)
    assert cb.allow() and cb.state == "HALF_OPEN"
    cb.record_success()
    assert cb.state == "CLOSED"
    print("circuit_breaker 三态 smoke PASS")

    # BreakerPool 语言隔离
    pool = BreakerPool()
    pool.register("python", threshold=2, cooldown=0.1)
    pool.register("go", threshold=2, cooldown=0.1)

    py_cb = pool.get("python")
    go_cb = pool.get("go")

    # 烧断 Python
    py_cb.record_failure("deepseek timeout")
    py_cb.record_failure("deepseek timeout")
    assert not py_cb.allow()
    assert py_cb.state == "OPEN"

    # Go 不受影响
    assert go_cb.allow()
    assert go_cb.state == "CLOSED"

    print(f"BreakerPool 语言隔离 smoke PASS: Python={py_cb.state}, Go={go_cb.state}")

    # 文件持久化
    with tempfile.TemporaryDirectory() as td:
        persist = str(Path(td) / ".breaker_state.json")
        pool2 = BreakerPool(_persist_path=persist)
        pool2.register("python", threshold=2, cooldown=0.1)
        pool2.get("python").record_failure("test")
        pool2._save()  # 显式持久化（生产环境由 app.py 在 AI 调用后调用）
        # 重新加载
        pool3 = BreakerPool(_persist_path=persist)
        pool3.register("python", threshold=2, cooldown=0.1)
        assert pool3.get("python").failures == 1
        print("BreakerPool 持久化 smoke PASS")

    # any_open
    assert "python" in pool.any_open()
    assert "go" not in pool.any_open()

    # reset
    pool.reset("python")
    assert pool.get("python").state == "CLOSED"

    print("circuit_breaker + BreakerPool 全部 smoke PASS")
