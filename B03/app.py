"""B03 FastAPI 子应用：真实天气证据 API 与页面（挂载于 /B03，见 run.py）。

每次 /api/weather 都真实发起外部 HTTP 请求（不写死 JSON），
返回 weather_evidence 并持久化到独立的 weather_evidence.db。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import evidence_store
from weather_client import fetch_weather, get_config

STATIC_DIR = Path(__file__).resolve().parent / "static"

b03_app = FastAPI(title="GreenMate B03 — 天气证据")


@b03_app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@b03_app.get("/api/weather")
def weather(location: str = "", language: str = ""):
    """真实调用外部天气 API 并返回 weather_evidence（成功/失败都入库）。"""
    if not location.strip():
        raise HTTPException(status_code=400, detail="location 不能为空（如：北京 / 上海 / 39.9,116.4）")
    evidence = fetch_weather(location.strip(), language or None)
    conn = evidence_store.connect()
    try:
        evidence_store.init_db(conn)
        evidence_store.insert_evidence(conn, evidence)
    finally:
        conn.close()
    return evidence


@b03_app.get("/api/evidence")
def evidence_list(limit: int = 20):
    """外部天气证据历史（独立存储，与 B02 本地模拟历史分离）。"""
    conn = evidence_store.connect()
    try:
        evidence_store.init_db(conn)
        rows = evidence_store.list_evidence(conn, max(1, min(limit, 200)))
        total = evidence_store.count_evidence(conn)
    finally:
        conn.close()
    return {
        "total": total,
        "items": rows,
        "note": "data_source=external_api，存储在 B03/data/weather_evidence.db，与本地模拟历史（B02）分离",
    }


@b03_app.get("/api/config")
def config():
    """当前 provider 配置（Key 脱敏，只返回是否已配置）。"""
    try:
        cfg = get_config()
        return {
            "provider": cfg["provider"],
            "api_key_configured": bool(cfg["api_key"]),
            "timeout": cfg["timeout"],
            "language": cfg["language"],
            "note": "qweather 需要 API Key；open_meteo 无需 Key",
        }
    except Exception as e:
        return {"error": str(e)}


b03_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="b03_static")
