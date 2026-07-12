"""配置加载与路径解析 —— 无状态纯函数（逐字移植自 app.py:58-78，去前导下划线）。"""
from __future__ import annotations
import json
from pathlib import Path


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def default_config_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "references" / "config.example.json")


def resolve_cache_dir(cache_dir: str, config_path: str) -> str:
    p = Path(cache_dir or "data/.cache")
    if p.is_absolute():
        return str(p)
    cfg = Path(config_path) if config_path else None
    default_cfg = Path(default_config_path()).resolve()
    is_default = cfg and cfg.exists() and cfg.resolve() == default_cfg
    base = Path(__file__).resolve().parents[2] if is_default or not (cfg and cfg.exists()) else cfg.resolve().parent
    return str(base / p)


def model_ver(models: list[dict]) -> str:
    return json.dumps(models, sort_keys=True)[:32]