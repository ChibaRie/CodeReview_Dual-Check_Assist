"""CQRS 读写隔离：读缓存 / 写新报告。"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from dataclasses import dataclass


@dataclass
class CQRSRouter:
    cache_dir: str
    ttl_days: int = 7

    def _path(self, key: str) -> Path:
        d = Path(self.cache_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.json"

    def try_read(self, key: str) -> dict | None:
        p = self._path(key)
        if not p.exists():
            return None
        if time.time() - p.stat().st_mtime > self.ttl_days * 86400:
            p.unlink(missing_ok=True)
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def write(self, key: str, report: dict) -> None:
        self._path(key).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def make_key(code: str, lang: str, model_ver: str) -> str:
    return hashlib.sha256(f"{code}::{lang}::{model_ver}".encode()).hexdigest()[:16]


if __name__ == "__main__":
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        r = CQRSRouter(td, ttl_days=1)
        key = make_key("print(1)", "python", "v1")
        assert r.try_read(key) is None
        r.write(key, {"ok": True})
        assert r.try_read(key) == {"ok": True}
        # stale
        p = r._path(key)
        os.utime(p, (0, 0))
        assert r.try_read(key) is None
    print("cqrs_router smoke PASS")
