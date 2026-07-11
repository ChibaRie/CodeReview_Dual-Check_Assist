"""熔断器 + BreakerPool 单元测试。v0.9"""
import json
import time
from pathlib import Path

import pytest
from circuit_breaker import BreakerPool, CircuitBreaker, create_pool


class TestCircuitBreaker:
    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.state == "CLOSED"
        assert cb.failures == 0

    def test_allow_closed(self):
        cb = CircuitBreaker()
        assert cb.allow() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(threshold=2, cooldown=60)
        cb.record_failure("timeout")
        assert cb.state == "CLOSED"
        cb.record_failure("timeout")
        assert cb.state == "OPEN"
        assert not cb.allow()

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(threshold=1, cooldown=0.05)
        cb.record_failure("err")
        assert cb.state == "OPEN"
        time.sleep(0.1)
        assert cb.allow() is True
        assert cb.state == "HALF_OPEN"

    def test_half_open_success_resets(self):
        cb = CircuitBreaker(threshold=1, cooldown=0.05)
        cb.record_failure("err")
        time.sleep(0.1)
        cb.allow()
        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.failures == 0

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(threshold=1, cooldown=0.05)
        cb.record_failure("err1")
        time.sleep(0.1)
        cb.allow()
        cb.record_failure("err2")
        assert cb.state == "OPEN"

    def test_record_success_in_closed(self):
        cb = CircuitBreaker()
        cb.record_success()
        assert cb.failures == 0

    def test_last_error_recorded(self):
        cb = CircuitBreaker(threshold=1)
        cb.record_failure("deepseek timeout")
        assert "deepseek" in cb.last_error

    def test_to_dict_from_dict(self):
        cb = CircuitBreaker(threshold=3, cooldown=30)
        cb.record_failure("test")
        d = cb.to_dict()
        cb2 = CircuitBreaker.from_dict(d)
        assert cb2.threshold == 3
        assert cb2.failures == 1
        assert cb2.last_error == "test"

    # 边界测试

    def test_threshold_zero(self):
        """threshold=0：第一次失败立即 OPEN"""
        cb = CircuitBreaker(threshold=0)
        cb.record_failure("e")
        assert cb.state == "OPEN"

    def test_very_long_cooldown(self):
        """cooldown 很大的情况"""
        cb = CircuitBreaker(threshold=1, cooldown=999999)
        cb.record_failure("e")
        assert cb.state == "OPEN"
        assert not cb.allow()

    def test_record_failure_no_reason(self):
        cb = CircuitBreaker()
        cb.record_failure()
        assert cb.failures == 1


class TestBreakerPool:
    def test_register_and_get(self):
        pool = BreakerPool()
        pool.register("python", threshold=2, cooldown=30)
        cb = pool.get("python")
        assert cb.threshold == 2
        assert cb.cooldown == 30

    def test_default_config_for_unregistered(self):
        pool = BreakerPool(_default_config={"threshold": 5, "cooldown": 120})
        cb = pool.get("unknown_lang")
        assert cb.threshold == 5
        assert cb.cooldown == 120

    def test_language_isolation(self):
        pool = BreakerPool()
        pool.register("python", threshold=1, cooldown=0.05)
        pool.register("go", threshold=1, cooldown=0.05)

        # 烧断 Python
        pool.get("python").record_failure("err")
        assert pool.get("python").state == "OPEN"

        # Go 不受影响
        assert pool.get("go").state == "CLOSED"

    def test_status(self):
        pool = BreakerPool()
        pool.register("python")
        pool.register("go")
        s = pool.status()
        assert "python" in s
        assert "go" in s
        assert s["python"]["state"] == "CLOSED"

    def test_any_open(self):
        pool = BreakerPool()
        pool.register("python", threshold=1)
        pool.register("go", threshold=5)
        pool.get("python").record_failure("e")
        assert "python" in pool.any_open()
        assert "go" not in pool.any_open()

    def test_reset_specific_language(self):
        pool = BreakerPool()
        pool.register("python", threshold=1)
        pool.register("go")
        pool.get("python").record_failure("e")
        pool.reset("python")
        assert pool.get("python").state == "CLOSED"
        assert pool.get("python").failures == 0

    def test_reset_all(self):
        pool = BreakerPool()
        pool.register("python", threshold=1)
        pool.register("go", threshold=1)
        pool.get("python").record_failure("e")
        pool.get("go").record_failure("e")
        pool.reset()
        assert pool.get("python").state == "CLOSED"
        assert pool.get("go").state == "CLOSED"

    def test_pool_record_failure(self):
        pool = BreakerPool()
        pool.register("python", threshold=2)
        pool.record_failure("python", "api down")
        assert pool.get("python").failures == 1

    def test_pool_record_success(self):
        pool = BreakerPool()
        pool.register("python", threshold=1, cooldown=0.05)
        pool.record_failure("python", "err")
        time.sleep(0.1)
        pool.get("python").allow()
        pool.record_success("python")
        assert pool.get("python").state == "CLOSED"

    # 文件持久化测试

    def test_persistence_save_and_load(self, temp_dir):
        persist = str(temp_dir / "breaker_state.json")
        pool = BreakerPool(_persist_path=persist)
        pool.register("python", threshold=2)
        pool.get("python").record_failure("test error")
        pool._save()

        # 重新加载
        pool2 = BreakerPool(_persist_path=persist)
        pool2.register("python", threshold=2)
        assert pool2.get("python").failures == 1
        assert pool2.get("python").last_error == "test error"

    def test_persistence_empty_file(self, temp_dir):
        persist = str(temp_dir / "nonexistent.json")
        pool = BreakerPool(_persist_path=persist)
        # 不存在的文件不报错
        assert pool.status() == {}

    def test_persistence_corrupted_file(self, temp_dir):
        persist = str(temp_dir / "breaker_state.json")
        persist_file = Path(persist)
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        persist_file.write_text("not valid json", encoding="utf-8")
        pool = BreakerPool(_persist_path=persist)
        # 损坏的文件不报错
        assert pool.status() == {}


class TestCreatePool:
    def test_create_from_config(self):
        config = {
            "breaker": {
                "default": {"threshold": 3, "cooldown": 60},
                "per_language": {
                    "python": {"threshold": 2, "cooldown": 10},
                    "java": {"threshold": 5, "cooldown": 120},
                },
            }
        }
        pool = create_pool(config)
        assert pool.get("python").threshold == 2
        assert pool.get("java").threshold == 5
        assert pool.get("go").threshold == 3  # default
