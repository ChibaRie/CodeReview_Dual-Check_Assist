"""config 纯函数逐字移植等价 —— oracle = fixtures/config_cache_dir.json（重构前旧实现快照）。"""
import json
from pathlib import Path

import pytest

from config import resolve_cache_dir

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "config_cache_dir.json"


def _load_cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: f"cd={c['cache_dir']!r},cp={c['config_path']!r}")
def test_resolve_cache_dir_matches_snapshot(case):
    result = resolve_cache_dir(case["cache_dir"], case["config_path"])
    assert result == case["expected"], (
        f"resolve_cache_dir({case['cache_dir']!r}, {case['config_path']!r}) "
        f"= {result!r}, 快照期望 {case['expected']!r}（移植漂移）"
    )
