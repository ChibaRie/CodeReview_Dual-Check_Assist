"""熔断器：AI 子系统健康闸门。"""
from __future__ import annotations
import time
from dataclasses import dataclass, field


@dataclass
class CircuitBreaker:
    threshold: int = 3
    cooldown: float = 60.0
    state: str = field(default="CLOSED")
    failures: int = field(default=0)
    opened_at: float = field(default=0.0)

    def allow(self) -> bool:
        now = time.time()
        if self.state == "OPEN":
            if now - self.opened_at >= self.cooldown:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.state = "OPEN"
            self.opened_at = time.time()


if __name__ == "__main__":
    cb = CircuitBreaker(threshold=2, cooldown=0.1)
    assert cb.allow()
    cb.record_failure()
    cb.record_failure()
    assert not cb.allow()
    time.sleep(0.15)
    assert cb.allow() and cb.state == "HALF_OPEN"
    cb.record_success()
    assert cb.state == "CLOSED"
    print("circuit_breaker smoke PASS")
