"""CQRS Router 单元测试 + 边界。v0.9"""
import json
import time
from pathlib import Path

import pytest
from cqrs_router import CQRSRouter, CacheStats, make_key


class TestCacheStats:
    def test_defaults(self):
        s = CacheStats()
        assert s.hits == 0 and s.misses == 0

    def test_hit_rate_zero_access(self):
        s = CacheStats()
        assert s.hit_rate == 0.0

    def test_hit_rate(self):
        s = CacheStats(hits=7, misses=3, total_access=10)
        assert s.hit_rate == 0.7

    def test_summary(self):
        s = CacheStats(hits=5, misses=5, total_access=10)
        assert "50%" in s.summary()


class TestMakeKey:
    def test_deterministic(self):
        k1 = make_key("x=1", "python", "v1")
        k2 = make_key("x=1", "python", "v1")
        assert k1 == k2

    def test_different_code(self):
        k1 = make_key("x=1", "python", "v1")
        k2 = make_key("x=2", "python", "v1")
        assert k1 != k2

    def test_different_lang(self):
        k1 = make_key("x=1", "python", "v1")
        k2 = make_key("x=1", "go", "v1")
        assert k1 != k2

    def test_full_length(self):
        """全量 SHA256 = 64 hex chars"""
        k = make_key("test", "python", "v1")
        assert len(k) == 64

    # 边界

    def test_empty_code(self):
        k = make_key("", "python", "v1")
        assert len(k) == 64

    def test_unicode_code(self):
        k = make_key("你好世界", "python", "v1")
        assert len(k) == 64

    def test_very_long_code(self):
        k = make_key("x" * 100000, "python", "v1")
        assert len(k) == 64


class TestCQRSRouter:
    def test_read_miss(self, temp_dir):
        r = CQRSRouter(str(temp_dir))
        assert r.try_read("no_such_key") is None

    def test_write_and_read(self, temp_dir):
        r = CQRSRouter(str(temp_dir))
        r.write("key1", {"risk": "可合并", "findings": []}, lang="python")
        result = r.try_read("key1")
        assert result == {"risk": "可合并", "findings": []}

    def test_write_with_code_lines(self, temp_dir):
        r = CQRSRouter(str(temp_dir))
        r.write("k", {"x": 1}, lang="python", code_lines=200)
        # 验证元数据
        cache_file = Path(temp_dir) / "k.json"
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data["_meta"]["code_lines"] == 200
        assert data["_meta"]["lang"] == "python"

    def test_stats_tracking(self, temp_dir):
        r = CQRSRouter(str(temp_dir))
        r.write("k", {"a": 1})
        r.try_read("k")  # hit
        r.try_read("no_key")  # miss
        s = r.stats()
        assert s.hits == 1
        assert s.misses >= 1

    def test_ttl_expiry(self, temp_dir):
        r = CQRSRouter(str(temp_dir), ttl_days=0)  # 立即过期
        r.write("k", {"x": 1})
        # 设置 created_at 为 0（epoch）模拟 TTL 过期
        cache_file = Path(temp_dir) / "k.json"
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        data["_meta"]["created_at"] = 0
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        assert r.try_read("k") is None

    def test_old_format_compatibility(self, temp_dir):
        """兼容旧格式（无 _meta 包裹的裸 dict）"""
        cache_file = Path(temp_dir) / "old_key.json"
        cache_file.write_text(json.dumps({"risk": "可合并"}), encoding="utf-8")
        # 设置足够新的 mtime 避免 TTL 过期
        r = CQRSRouter(str(temp_dir), ttl_days=365)
        result = r.try_read("old_key")
        assert result == {"risk": "可合并"}

    # 边界测试

    def test_empty_dict(self, temp_dir):
        r = CQRSRouter(str(temp_dir))
        r.write("empty", {}, lang="")
        assert r.try_read("empty") == {}

    def test_large_report(self, temp_dir):
        r = CQRSRouter(str(temp_dir))
        large = {"findings": [{"line": i, "kind": "test"} for i in range(1000)]}
        r.write("large", large)
        result = r.try_read("large")
        assert len(result["findings"]) == 1000

    def test_unicode_content(self, temp_dir):
        r = CQRSRouter(str(temp_dir))
        r.write("unicode", {"message": "你好世界 🚀"})
        result = r.try_read("unicode")
        assert "你好世界" in result["message"]

    def test_concurrent_reads(self, temp_dir):
        """并发读取（单线程串行验证，避免 stats 文件竞争）"""
        r = CQRSRouter(str(temp_dir))
        r.write("shared", {"v": 1})
        # 10 次串行读取验证一致性
        for _ in range(10):
            result = r.try_read("shared")
            assert result == {"v": 1}

    def test_concurrent_write_read(self, temp_dir):
        """并发写入不应崩溃"""
        r = CQRSRouter(str(temp_dir))
        import threading

        errors = []

        def _write(i):
            try:
                r.write(f"k{i}", {"i": i})
                r.try_read(f"k{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"concurrent write errors: {errors}"
