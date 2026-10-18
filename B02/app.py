"""B02 FastAPI 子应用：历史数据查询 API 与页面。

挂载于 /B02（见 main.py 组合入口），不改动 B01 任何代码。
数据源：SQLite（B02/data/greenmate_b02.db），每次请求独立连接，
程序重启后历史记录仍然存在。
"""

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from simulator import DISTURBANCES, SAMPLE_INTERVAL_MINUTES, generate_samples

STATIC_DIR = Path(__file__).resolve().parent / "static"

b02_app = FastAPI(title="GreenMate B02 — 数据记忆")


class AppendRequest(BaseModel):
    hours: float


def parse_ts(s):
    """宽松解析 'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD HH:MM:SS'。"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError("时间格式应为 YYYY-MM-DD [HH:MM[:SS]]: %s" % s)


@b02_app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@b02_app.get("/api/meta")
def meta():
    conn = db.connect()
    try:
        n = db.count_samples(conn)
        first = conn.execute("SELECT MIN(timestamp) AS t FROM environment_samples").fetchone()["t"]
        last = conn.execute("SELECT MAX(timestamp) AS t FROM environment_samples").fetchone()["t"]
    finally:
        conn.close()
    return {
        "dataset": "greenmate_b02",
        "sample_interval_minutes": SAMPLE_INTERVAL_MINUTES,
        "expected_total": 336,
        "actual_total": n,
        "first_timestamp": first,
        "last_timestamp": last,
        "source_type": "SIMULATED",
        "disturbance_count": len(DISTURBANCES),
        "db_path": str(db.DB_PATH),
    }


@b02_app.get("/api/series")
def series(start: str = "", end: str = ""):
    try:
        s = parse_ts(start) if start.strip() else None
        e = parse_ts(end) if end.strip() else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    conn = db.connect()
    try:
        rows = db.query_series(conn, s, e)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail="时间窗口内无数据（请先运行 python B02/generate.py 生成数据）")
    return {"count": len(rows), "samples": rows}


@b02_app.get("/api/stats")
def stats(start: str = "", end: str = ""):
    try:
        s = parse_ts(start) if start.strip() else None
        e = parse_ts(end) if end.strip() else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    conn = db.connect()
    try:
        result = db.query_stats(conn, s, e)
    finally:
        conn.close()
    return result


@b02_app.get("/api/disturbances")
def disturbances():
    conn = db.connect()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, type, start_ts, end_ts, description FROM disturbance_events ORDER BY start_ts"
        ).fetchall()]
    finally:
        conn.close()
    return {
        "count": len(rows),
        "disturbances": rows,
        "note": "sim_scenario 仅为模拟器元数据，不作为标签",
    }


@b02_app.post("/api/append")
def append(req: AppendRequest):
    """从库里最后时间点继续追加 N 小时新样本（演示持久化追加）。"""
    if req.hours <= 0:
        raise HTTPException(status_code=400, detail="hours 必须为正数")
    conn = db.connect()
    try:
        db.init_db(conn)
        last = db.query_last_timestamp(conn)
        if not last:
            raise HTTPException(status_code=400, detail="库为空，请先运行 python B02/generate.py")
        start_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S") + timedelta(minutes=SAMPLE_INTERVAL_MINUTES)
        n = int(req.hours * 60 / SAMPLE_INTERVAL_MINUTES)
        rows = generate_samples(start_dt, n)
        db.insert_samples(conn, rows)
        new_last = db.query_last_timestamp(conn)
        count = db.count_samples(conn)
    finally:
        conn.close()
    return {"appended": len(rows), "from": last, "to": new_last, "total_now": count}


b02_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="b02_static")
