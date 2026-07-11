"""舱壁隔离：双线程池隔离大文件/小文件评审。v0.5"""
from __future__ import annotations
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class BulkheadStats:
    """舱壁运行统计。"""
    normal_submitted: int = 0
    normal_completed: int = 0
    large_submitted: int = 0
    large_completed: int = 0
    normal_total_wait_ms: float = 0.0
    large_total_wait_ms: float = 0.0

    @property
    def normal_avg_wait_ms(self) -> float:
        if self.normal_completed == 0:
            return 0.0
        return self.normal_total_wait_ms / self.normal_completed

    @property
    def large_avg_wait_ms(self) -> float:
        if self.large_completed == 0:
            return 0.0
        return self.large_total_wait_ms / self.large_completed


@dataclass
class BulkheadExecutor:
    """舱壁隔离执行器。

    两个独立线程池：
      - normal_pool: max_workers=10，处理 ≤500 行的文件
      - large_pool:  max_workers=2，  处理 >500 行的文件

    大文件堵死在 large_pool，不影响 normal_pool 中小文件的快速响应。

    ┌─────────────────────────┐
    │      请求入口             │
    └────────┬────────────────┘
             │
    ┌────────▼────────┐
    │  判断文件行数    │
    └───┬────────┬────┘
        │        │
   ≤500行     >500行
        │        │
        ▼        ▼
 ┌──────────┐ ┌──────────┐
 │ normal   │ │ large    │
 │ pool     │ │ pool     │
 │ (10 并发) │ │ (2 并发) │
 └────┬─────┘ └────┬─────┘
      │            │
      ▼            ▼
 ┌──────────┐ ┌──────────┐
 │ 快速返回  │ │ 慢速返回  │
 │ < 3s     │ │ < 15s    │
 └──────────┘ └──────────┘
    """

    normal_pool: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=10))
    large_pool: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=2))
    line_threshold: int = 500
    _stats: BulkheadStats = field(default_factory=BulkheadStats)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _futures: list[Future] = field(default_factory=list)

    def classify(self, code: str) -> str:
        """根据代码行数分类：'normal' 或 'large'。"""
        lines = code.count("\n") + 1
        return "large" if lines > self.line_threshold else "normal"

    def submit(self, fn: Callable, code: str, lang: str, **kwargs) -> Future:
        """提交评审任务到对应的线程池。

        返回 Future，调用方可通过 .result() 获取结果。
        自动选择池：≤500 行 → normal_pool，>500 行 → large_pool。
        """
        category = self.classify(code)
        pool = self.large_pool if category == "large" else self.normal_pool

        with self._lock:
            if category == "large":
                self._stats.large_submitted += 1
            else:
                self._stats.normal_submitted += 1

        t0 = time.perf_counter()

        def _wrapped():
            try:
                result = fn(code, lang, **kwargs)
                elapsed = (time.perf_counter() - t0) * 1000
                with self._lock:
                    if category == "large":
                        self._stats.large_completed += 1
                        self._stats.large_total_wait_ms += elapsed
                    else:
                        self._stats.normal_completed += 1
                        self._stats.normal_total_wait_ms += elapsed
                return result
            except Exception:
                elapsed = (time.perf_counter() - t0) * 1000
                with self._lock:
                    if category == "large":
                        self._stats.large_completed += 1
                        self._stats.large_total_wait_ms += elapsed
                    else:
                        self._stats.normal_completed += 1
                        self._stats.normal_total_wait_ms += elapsed
                raise

        future = pool.submit(_wrapped)
        self._futures.append(future)
        return future

    def stats(self) -> dict:
        """返回当前舱壁统计信息。"""
        with self._lock:
            return {
                "normal_pool": {
                    "max_workers": 10,
                    "submitted": self._stats.normal_submitted,
                    "completed": self._stats.normal_completed,
                    "avg_wait_ms": round(self._stats.normal_avg_wait_ms, 1),
                },
                "large_pool": {
                    "max_workers": 2,
                    "submitted": self._stats.large_submitted,
                    "completed": self._stats.large_completed,
                    "avg_wait_ms": round(self._stats.large_avg_wait_ms, 1),
                },
                "line_threshold": self.line_threshold,
            }

    def shutdown(self, wait: bool = True) -> None:
        """关闭两个线程池。"""
        self.normal_pool.shutdown(wait=wait)
        self.large_pool.shutdown(wait=wait)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown(wait=True)


# ── 冒烟测试 ──────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    def dummy_review(code: str, lang: str, **kw) -> dict:
        """模拟评审：行数越多等待越久。"""
        lines = code.count("\n") + 1
        delay = 0.05 if lines <= 500 else 0.3
        time.sleep(delay)
        return {"lines": lines, "pool": "large" if lines > 500 else "normal", "delay": delay}

    small_code = "def f():\n    pass\n" * 3  # 3 lines
    large_code = "x = 1\n" * 600  # 600 lines

    # 小文件分类
    with BulkheadExecutor() as bh:
        assert bh.classify(small_code) == "normal"
        assert bh.classify(large_code) == "large"
        print(f"分类 smoke PASS: small→{bh.classify(small_code)}, large→{bh.classify(large_code)}")

    # 舱壁隔离：大文件不阻塞小文件
    with BulkheadExecutor() as bh:
        # 先提交 3 个大文件（占用 large_pool 的 2 个线程 + 1 个排队）
        large_futures = [bh.submit(dummy_review, large_code, "python") for _ in range(3)]
        # 同时提交 5 个小文件（normal_pool 有 10 个线程，全部并行）
        small_futures = [bh.submit(dummy_review, small_code, "python") for _ in range(5)]

        t0 = time.perf_counter()
        small_results = [f.result() for f in small_futures]
        small_elapsed = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        large_results = [f.result() for f in large_futures]
        large_elapsed = (time.perf_counter() - t1) * 1000

        print(f"小文件 5 个完成耗时: {small_elapsed:.0f} ms（目标 < 3s）")
        print(f"大文件 3 个完成耗时: {large_elapsed:.0f} ms")
        assert small_elapsed < 3000, f"小文件等待超时: {small_elapsed:.0f}ms"
        print(f"舱壁隔离 smoke PASS: 小文件不受大文件阻塞")

    # 统计
    with BulkheadExecutor() as bh:
        for _ in range(4):
            bh.submit(dummy_review, small_code, "python")
        for _ in range(2):
            bh.submit(dummy_review, large_code, "python")
        for f in bh._futures:
            f.result()
        s = bh.stats()
        assert s["normal_pool"]["completed"] == 4
        assert s["large_pool"]["completed"] == 2
        assert s["normal_pool"]["avg_wait_ms"] < s["large_pool"]["avg_wait_ms"]
        print(f"统计 smoke PASS: normal={s['normal_pool']}, large={s['large_pool']}")

    print("bulkhead 全部 smoke PASS")
