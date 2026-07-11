"""系统健康度自检：生成 system/status.md 仪表盘。"""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def run(cache_dir: str, status_path: str) -> dict:
    """扫描缓存和规则文件，生成健康度报告并写入 status.md。"""
    now = datetime.now(timezone(timedelta(hours=8)))
    status: dict = {"generated_at": now.isoformat(), "cache": {}, "rules": {}, "health": {}}

    # ── 缓存健康度 ──
    cp = Path(cache_dir)
    cache_files = [f for f in cp.glob("*.json") if f.name != ".stats.json"] if cp.exists() else []
    total_size = sum(f.stat().st_size for f in cache_files)
    expired = sum(1 for f in cache_files
                  if now.timestamp() - f.stat().st_mtime > 7 * 86400)

    # 读取 CQRS 访问统计
    stats_path = cp / ".stats.json" if cp.exists() else None
    cache_stats = {}
    if stats_path and stats_path.exists():
        try:
            cache_stats = json.loads(stats_path.read_text(encoding="utf-8"))
        except Exception:
            cache_stats = {}

    status["cache"] = {
        "dir": str(cp), "files": len(cache_files),
        "total_size_kb": round(total_size / 1024, 1), "expired": expired,
        "healthy": expired < max(len(cache_files) // 2, 1),
        "hits": cache_stats.get("hits", 0),
        "misses": cache_stats.get("misses", 0),
        "total_access": cache_stats.get("total_access", 0),
    }

    # ── 规则文件完整性 ──
    rules_dir = Path(__file__).resolve().parents[1] / "references" / "rules"
    rule_files = {}
    for rf in sorted(rules_dir.glob("*.yaml")):
        try:
            content = rf.read_text(encoding="utf-8")
            rule_files[rf.name] = {"exists": True, "size": len(content),
                                   "has_rules": "kind:" in content}
        except Exception:
            rule_files[rf.name] = {"exists": True, "error": "unreadable"}
    status["rules"] = {"dir": str(rules_dir), "files": rule_files,
                       "count": len(rule_files), "all_present": len(rule_files) >= 2}

    # ── 熔断器状态 ──
    breaker_path = cp / ".breaker_state.json" if cp.exists() else None
    breaker_status = {}
    if breaker_path and breaker_path.exists():
        try:
            breaker_status = json.loads(breaker_path.read_text(encoding="utf-8"))
        except Exception:
            breaker_status = {}
    open_langs = [lang for lang, s in breaker_status.items() if s.get("state") == "OPEN"]
    status["breaker"] = {
        "total": len(breaker_status),
        "open": len(open_langs),
        "open_languages": open_langs,
        "details": breaker_status,
    }

    # ── 整体评估 ──
    cache_ok = status["cache"]["healthy"]
    rules_ok = status["rules"]["all_present"]
    breaker_ok = len(open_langs) == 0
    status["health"] = {
        "cache": "健康" if cache_ok else "需关注",
        "rules": "完整" if rules_ok else "缺失",
        "breaker": "健康" if breaker_ok else f"需关注（{len(open_langs)} 个 OPEN）",
        "overall": "健康" if (cache_ok and rules_ok and breaker_ok) else "需关注",
    }

    # ── 写入 status.md ──
    hit_rate = 0.0
    if cache_stats.get("total_access", 0) > 0:
        hit_rate = cache_stats.get("hits", 0) / cache_stats["total_access"]
    md_lines = [
        "# System Status", "",
        f"- Generated: {now.isoformat()}",
        f"- Cache dir: `{cp}`",
        f"- Cache files: {len(cache_files)} (expired: {expired})",
        f"- Cache total size: {round(total_size / 1024, 1)} KB",
        f"- CQRS 访问: 命中 {cache_stats.get('hits', 0)} / 共 {cache_stats.get('total_access', 0)} 次 "
        f"(命中率 {hit_rate:.0%})",
        f"- 熔断器: {len(breaker_status)} 个语言，{len(open_langs)} 个 OPEN"
        + (f" ({', '.join(open_langs)})" if open_langs else ""),
        f"- Rule files: {', '.join(status['rules']['files'].keys()) or 'none'}",
        "", "## Health", "",
        "| Dimension | Status |", "| --- | --- |",
        f"| Cache | {status['health']['cache']} |",
        f"| Rules | {status['health']['rules']} |",
        f"| Breaker | {status['health']['breaker']} |",
        f"| **Overall** | **{status['health']['overall']}** |", "",
    ]
    status_path_obj = Path(status_path)
    status_path_obj.parent.mkdir(parents=True, exist_ok=True)
    status_path_obj.write_text("\n".join(md_lines), encoding="utf-8")

    return status


if __name__ == "__main__":
    import sys
    cd = sys.argv[1] if len(sys.argv) > 1 else "data/.cache"
    sp = sys.argv[2] if len(sys.argv) > 2 else "system/status.md"
    result = run(cd, sp)
    print(json.dumps(result, ensure_ascii=False, indent=2))
