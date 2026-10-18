"""SQLite 持久化层：建库、建表、写入、commit、查询。

- 数据库文件：B02/data/greenmate_b02.db（与进程无关，关闭程序后仍在）；
- timestamp 为 TEXT 格式 'YYYY-MM-DD HH:MM:SS'（同格式字典序即时间序）；
- UNIQUE 约束兜底防重复采样点；
- 所有写入显式 commit。
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "greenmate_b02.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS environment_samples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL UNIQUE,           -- 固定30分钟采样点
    temperature  REAL NOT NULL,
    humidity     REAL NOT NULL,
    light        REAL NOT NULL,
    source_type  TEXT NOT NULL DEFAULT 'SIMULATED',
    sim_scenario TEXT NOT NULL DEFAULT 'normal'  -- 模拟器元数据（normal/扰动id/ramp），不是标签
);
CREATE INDEX IF NOT EXISTS idx_samples_timestamp ON environment_samples(timestamp);

CREATE TABLE IF NOT EXISTS disturbance_events (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    start_ts    TEXT NOT NULL,
    end_ts      TEXT NOT NULL,
    description TEXT NOT NULL
);
"""


def connect():
    """新建一个 SQLite 连接（每次查询独立连接，等价于程序重启后的新会话）。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def insert_samples(conn, rows):
    conn.executemany(
        "INSERT OR REPLACE INTO environment_samples "
        "(timestamp, temperature, humidity, light, source_type, sim_scenario) "
        "VALUES (:timestamp, :temperature, :humidity, :light, :source_type, :sim_scenario)",
        rows,
    )
    conn.commit()  # 显式 commit：确保持久化落盘


def insert_disturbances(conn, disturbances):
    conn.executemany(
        "INSERT OR REPLACE INTO disturbance_events (id, type, start_ts, end_ts, description) "
        "VALUES (:id, :type, :start, :end, :description)",
        [{
            "id": d["id"], "type": d["type"],
            "start": d["start"].strftime("%Y-%m-%d %H:%M:%S"),
            "end": d["end"].strftime("%Y-%m-%d %H:%M:%S"),
            "description": d["description"],
        } for d in disturbances],
    )
    conn.commit()


def count_samples(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM environment_samples").fetchone()["n"]


def query_last_timestamp(conn):
    row = conn.execute("SELECT MAX(timestamp) AS ts FROM environment_samples").fetchone()
    return row["ts"]


def query_series(conn, start=None, end=None):
    """按时间窗口查询原始序列（升序）。start/end 为 'YYYY-MM-DD [HH:MM[:SS]]'。"""
    sql = ("SELECT timestamp, temperature, humidity, light, source_type, sim_scenario "
           "FROM environment_samples")
    params = []
    conds = []
    if start:
        conds.append("timestamp >= ?")
        params.append(start)
    if end:
        conds.append("timestamp <= ?")
        params.append(end)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY timestamp ASC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_stats(conn, start=None, end=None):
    """时间窗口统计：count、各字段 min/max/avg、趋势（窗口内最早/最晚各 12 个点均值对比）。"""
    rows = query_series(conn, start, end)
    if not rows:
        return {"count": 0, "note": "时间窗口内无数据"}
    fields = ("temperature", "humidity", "light")
    result = {
        "count": len(rows),
        "window": {"start": rows[0]["timestamp"], "end": rows[-1]["timestamp"]},
        "fields": {},
        "trend": {},
    }
    for f in fields:
        values = [r[f] for r in rows]
        result["fields"][f] = {
            "min": round(min(values), 1),
            "max": round(max(values), 1),
            "avg": round(sum(values) / len(values), 1),
        }
    if len(rows) >= 24:
        thresholds = {"temperature": 0.5, "humidity": 2.0, "light": 500}
        for f in fields:
            head = sum(r[f] for r in rows[:12]) / 12.0
            tail = sum(r[f] for r in rows[-12:]) / 12.0
            diff = tail - head
            thr = thresholds[f]
            if diff > thr:
                direction = "上升"
            elif diff < -thr:
                direction = "下降"
            else:
                direction = "平稳"
            result["trend"][f] = {
                "head_avg": round(head, 1),
                "tail_avg": round(tail, 1),
                "diff": round(diff, 1),
                "direction": direction,
            }
    else:
        result["trend"] = {"note": "样本少于 24 个，不计算趋势"}
    return result
