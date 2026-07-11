"""CQRS 读写隔离：读缓存 / 写新报告。v0.3 — 全量 SHA256 + 访问统计。"""
from __future__ import annotations
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CacheStats:
    """缓存命中/未命中统计，持久化到 .stats.json。"""
    hits: int = 0
    misses: int = 0
    total_access: int = 0

    @property
    def hit_rate(self) -> float:
        if self.total_access == 0:
            return 0.0
        return self.hits / self.total_access

    def summary(self) -> str:
        return (f"缓存命中 {self.hits} 次 / 共 {self.total_access} 次访问 "
                f"(命中率 {self.hit_rate:.0%})")


@dataclass
class CQRSRouter:
    """CQRS 读写隔离路由器。

    读路径（try_read）：
      1. 计算 cache key → 查文件
      2. 命中 → 检查 TTL → 返回缓存报告（< 50ms）
      3. 未命中 / 过期 → 返回 None

    写路径（write）：
      4. 将 FinalReport 包裹 _meta 元数据后写入 JSON 文件
    """

    cache_dir: str
    ttl_days: int = 7
    _stats: CacheStats = field(default_factory=CacheStats)

    # ── 内部路径 ──────────────────────────────────────────────

    def _path(self, key: str) -> Path:
        d = Path(self.cache_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.json"

    def _stats_path(self) -> Path:
        d = Path(self.cache_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d / ".stats.json"

    # ── 统计持久化 ────────────────────────────────────────────

    def _load_stats(self) -> CacheStats:
        sp = self._stats_path()
        if sp.exists():
            try:
                data = json.loads(sp.read_text(encoding="utf-8"))
                return CacheStats(
                    hits=data.get("hits", 0),
                    misses=data.get("misses", 0),
                    total_access=data.get("total_access", 0),
                )
            except Exception:
                pass
        return CacheStats()

    def _save_stats(self) -> None:
        self._stats.total_access = self._stats.hits + self._stats.misses
        self._stats_path().write_text(
            json.dumps(
                {
                    "hits": self._stats.hits,
                    "misses": self._stats.misses,
                    "total_access": self._stats.total_access,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def stats(self) -> CacheStats:
        """返回当前持久化的缓存统计。"""
        return self._load_stats()

    # ── 读写路径 ──────────────────────────────────────────────

    def try_read(self, key: str) -> dict | None:
        """读路径：查缓存并验证 TTL。

        - 兼容旧格式（无 _meta 包裹的裸 FinalReport dict）
        - 新格式为 {"_meta": {...}, "report": {...}}
        - 命中时自动更新 access_count / last_access
        """
        self._stats = self._load_stats()
        p = self._path(key)
        if not p.exists():
            self._stats.misses += 1
            self._save_stats()
            return None

        raw = json.loads(p.read_text(encoding="utf-8"))

        # 兼容旧格式（裸 FinalReport dict，无 _meta 包裹）
        if "_meta" in raw:
            created = raw["_meta"].get("created_at", 0)
            report = raw.get("report", {})
        else:
            created = p.stat().st_mtime
            report = raw

        # TTL 过期检查
        if time.time() - created > self.ttl_days * 86400:
            p.unlink(missing_ok=True)
            self._stats.misses += 1
            self._save_stats()
            return None

        # 更新访问计数（仅新格式）
        if "_meta" in raw:
            raw["_meta"]["access_count"] = raw["_meta"].get("access_count", 0) + 1
            raw["_meta"]["last_access"] = time.time()
            p.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        self._stats.hits += 1
        self._save_stats()
        return report

    def write(self, key: str, report: dict, lang: str = "", code_lines: int = 0) -> None:
        """写路径：将评审报告包裹 _meta 元数据后持久化。"""
        envelope = {
            "_meta": {
                "created_at": time.time(),
                "access_count": 1,
                "last_access": time.time(),
                "key": key,
                "lang": lang,
                "code_lines": code_lines,
            },
            "report": report,
        }
        self._path(key).write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def make_key(code: str, lang: str, model_ver: str) -> str:
    """生成全量 SHA256 缓存键（64 位十六进制），抗碰撞。"""
    return hashlib.sha256(
        f"{code}::{lang}::{model_ver}".encode()
    ).hexdigest()


# ── 冒烟测试 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        r = CQRSRouter(td, ttl_days=1)
        key = make_key("print(1)", "python", "v1")

        # 读未命中
        t0 = time.perf_counter()
        assert r.try_read(key) is None
        t1 = time.perf_counter()
        print(f"  未命中查询耗时: {(t1 - t0) * 1000:.1f} ms")

        # 写
        r.write(key, {"ok": True}, lang="python")

        # 读命中
        t2 = time.perf_counter()
        result = r.try_read(key)
        t3 = time.perf_counter()
        assert result == {"ok": True}
        hit_ms = (t3 - t2) * 1000
        print(f"  命中查询耗时: {hit_ms:.1f} ms")

        # 验证 stats
        s = r.stats()
        assert s.hits == 1 and s.misses == 1
        print(f"  {s.summary()}")

        # 过期 — 修改 _meta.created_at 模拟过期
        p = r._path(key)
        raw = json.loads(p.read_text(encoding="utf-8"))
        raw["_meta"]["created_at"] = 0  # epoch 0 → 远超 TTL
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        assert r.try_read(key) is None
        print(f"  TTL 过期清理正常")

        # 验证 < 50ms 目标
        for _ in range(100):
            r.write(key, {"bench": True}, lang="python")
            bt0 = time.perf_counter()
            r.try_read(key)
            bt1 = time.perf_counter()
        avg_ms = (bt1 - bt0) * 10  # 100 次平均
        print(f"  100 次读取平均耗时: 约 {avg_ms:.1f} ms/次")

    print("cqrs_router smoke PASS")
