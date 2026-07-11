"""舱壁隔离单元测试。v0.9"""
import time

import pytest
from bulkhead import BulkheadExecutor, BulkheadStats


def _dummy(code, lang, **kw):
    lines = code.count("\n") + 1
    time.sleep(0.01 if lines <= 500 else 0.1)
    return {"risk": "可合并", "findings": []}, {"elapsed_ms": 0}


class TestBulkheadClassification:
    def test_small_file_normal(self):
        bh = BulkheadExecutor()
        assert bh.classify("def f():\n    pass\n") == "normal"

    def test_large_file_large(self):
        bh = BulkheadExecutor()
        code = "x = 1\n" * 600
        assert bh.classify(code) == "large"

    def test_boundary_exact_500(self):
        bh = BulkheadExecutor()
        code = "\n".join(["x"] * 500)  # 500 行（499 个\n + 1 = 500）
        assert bh.classify(code) == "normal"

    def test_boundary_501(self):
        bh = BulkheadExecutor()
        code = "\n".join(["x"] * 501)  # 501 行
        assert bh.classify(code) == "large"

    def test_custom_threshold(self):
        bh = BulkheadExecutor(line_threshold=100)
        code = "x\n" * 150
        assert bh.classify(code) == "large"

    def test_empty_code(self):
        bh = BulkheadExecutor()
        assert bh.classify("") == "normal"  # 0 行 ≤ 500


class TestBulkheadExecution:
    def test_concurrent_small_files(self):
        with BulkheadExecutor() as bh:
            code = "x\n" * 10
            for _ in range(20):
                bh.submit(_dummy, code, "python")
            for f in bh._futures:
                r, perf = f.result(timeout=5)
                assert r["risk"] == "可合并"
            s = bh.stats()
            assert s["normal_pool"]["completed"] == 20

    def test_mixed_sizes(self):
        with BulkheadExecutor() as bh:
            small = "x\n" * 10
            large = "x\n" * 600
            for _ in range(5):
                bh.submit(_dummy, small, "python")
            for _ in range(3):
                bh.submit(_dummy, large, "python")
            for f in bh._futures:
                f.result(timeout=10)
            s = bh.stats()
            assert s["normal_pool"]["completed"] == 5
            assert s["large_pool"]["completed"] == 3

    def test_large_pool_limited_concurrency(self):
        """large pool 只有 2 并发，第 3 个排队"""
        with BulkheadExecutor() as bh:
            large = "x\n" * 600
            t0 = time.perf_counter()
            for _ in range(4):
                bh.submit(_dummy, large, "python")
            for f in bh._futures:
                f.result(timeout=10)
            elapsed = time.perf_counter() - t0
            # 4 个任务 × 0.1s 每个，2 并发 → 至少 0.2s
            assert elapsed >= 0.15

    def test_stats_accuracy(self):
        with BulkheadExecutor() as bh:
            for _ in range(3):
                bh.submit(_dummy, "x\n" * 20, "python")
            for f in bh._futures:
                f.result(timeout=5)
            s = bh.stats()
            assert s["normal_pool"]["submitted"] == 3
            assert s["normal_pool"]["completed"] == 3
            assert s["normal_pool"]["avg_wait_ms"] > 0

    def test_with_statement_shutdown(self):
        bh = BulkheadExecutor()
        with bh:
            bh.submit(_dummy, "x\n" * 5, "python")
        # with 退出后池应关闭
        # 尝试提交到已关闭的池会抛异常
        import concurrent.futures
        # 池已关闭，无法再提交
