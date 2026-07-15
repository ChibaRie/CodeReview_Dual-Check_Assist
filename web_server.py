"""DualCheck Code Web UI 后端 — FastAPI 入口。

注意：本文件不属于 skill/ 包，仅服务于当前项目的本地 Web UI。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from skill.scripts.config import default_config_path, load_config, resolve_cache_dir
from skill.scripts.circuit_breaker import BreakerPool, create_pool
from skill.scripts.health_check import run as health_check_run
from skill.scripts.reviewer import Reviewer
from skill.scripts.trend_analyzer import analyze as trend_analyze, fmt_trend_json
from skill.scripts.vector_store import VectorStore

app = FastAPI(title="DualCheck Code Web UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)

LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".js": "javascript",
    ".ts": "javascript",
}
LANG_PATTERN = r"^(python|java|go|javascript)$"


class ReviewRequest(BaseModel):
    code: str = Field(max_length=200_000)
    lang: str = Field(pattern=LANG_PATTERN)
    framework: str = Field(default="", max_length=100)
    api_key: str = Field(default="", max_length=500)
    use_cache: bool = True


class BatchRequest(BaseModel):
    directory: str = Field(max_length=500)
    lang: str = Field(default="python", pattern=LANG_PATTERN)
    framework: str = Field(default="", max_length=100)
    api_key: str = Field(default="", max_length=500)
    use_cache: bool = True
    line_threshold: int = Field(default=500, ge=1)


class BreakerResetRequest(BaseModel):
    lang: str = Field(default="", pattern=r"^(python|java|go|javascript)?$")


class BatchFileError:
    message = "文件评审失败"


_cache_dir_value: str | None = None


def _cache_dir() -> str:
    global _cache_dir_value
    if _cache_dir_value is None:
        config = load_config(default_config_path())
        _cache_dir_value = resolve_cache_dir(
            config.get("cache", {}).get("dir", "data/.cache"), ""
        )
    return _cache_dir_value


def _load_breaker_pool() -> BreakerPool:
    config = load_config(default_config_path())
    cache_dir = _cache_dir()
    persist_path = str(Path(cache_dir) / ".breaker_state.json")
    return create_pool(config, persist_path)


def _safe_directory(directory: str) -> Path:
    """解析并校验 batch 目录，拒绝明显的路径遍历序列。"""
    if ".." in directory or "~" in directory:
        raise ValueError("目录路径包含非法字符")
    p = Path(directory)
    if not p.is_dir():
        raise ValueError(f"{directory} 不是有效目录")
    return p


@app.post("/api/review")
def api_review(req: ReviewRequest) -> dict:
    try:
        reviewer = Reviewer()
        config_path = default_config_path()
        report, perf = reviewer.review(
            code=req.code,
            lang=req.lang,
            framework=req.framework,
            config_path=config_path,
            use_cache=req.use_cache,
            api_key=req.api_key,
        )
    except Exception as exc:
        logger.exception("review failed")
        raise HTTPException(status_code=500, detail="评审失败，请稍后重试") from exc
    out = report.__dict__.copy()
    out["_perf"] = perf
    return out


@app.post("/api/batch")
def api_batch(req: BatchRequest) -> dict:
    try:
        directory = _safe_directory(req.directory)
    except ValueError as exc:
        return {"error": str(exc)}

    files = sorted(
        [f for f in directory.iterdir() if f.is_file() and f.suffix in LANG_MAP]
    )
    results = []
    reviewer = Reviewer()
    config_path = default_config_path()
    for f in files:
        try:
            code = f.read_text(encoding="utf-8")
            lines = code.count("\n") + 1
            file_lang = LANG_MAP.get(f.suffix, req.lang)
            report, perf = reviewer.review(
                code=code,
                lang=file_lang,
                framework=req.framework,
                config_path=config_path,
                use_cache=req.use_cache,
                api_key=req.api_key,
            )
            results.append({
                "file": f.name,
                "lines": lines,
                "risk": report.risk,
                "elapsed_ms": perf["elapsed_ms"],
                "pool": "large" if lines > req.line_threshold else "normal",
                "perf": perf,
            })
        except Exception as exc:
            logger.exception("batch review failed for %s", f.name)
            results.append({
                "file": f.name,
                "lines": 0,
                "risk": "ERROR: 文件评审失败",
                "elapsed_ms": 0,
                "pool": "unknown",
                "perf": {},
            })
    return {
        "batch_summary": {
            "total_files": len(results),
            "small_files": sum(1 for r in results if r["pool"] == "normal"),
            "large_files": sum(1 for r in results if r["pool"] == "large"),
        },
        "files": results,
    }


@app.get("/api/health")
def api_health() -> dict:
    cache_dir = _cache_dir()
    status_path = str(Path(__file__).resolve().parent / "system" / "status.md")
    return health_check_run(cache_dir, status_path)


@app.get("/api/breaker")
def api_breaker() -> dict:
    pool = _load_breaker_pool()
    return pool.status()


@app.post("/api/breaker/reset")
def api_breaker_reset(req: BreakerResetRequest) -> dict:
    pool = _load_breaker_pool()
    pool.reset(req.lang)
    pool._save()
    return {"ok": True, "lang": req.lang or "all"}


@app.get("/api/vector/stats")
def api_vector_stats() -> dict:
    cache_dir = _cache_dir()
    vdb = str(Path(cache_dir) / "patterns.db")
    vstore = VectorStore(vdb)
    try:
        return vstore.stats()
    finally:
        vstore.close()


@app.get("/api/trend")
def api_trend() -> dict:
    try:
        cache_dir = _cache_dir()
        vdb = str(Path(cache_dir) / "patterns.db")
        report = trend_analyze(cache_dir, vdb)
        return json.loads(fmt_trend_json(report))
    except Exception as exc:
        logger.exception("trend report failed")
        raise HTTPException(status_code=500, detail="趋势报告生成失败") from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_server:app", host="127.0.0.1", port=8000, reload=True)
