"""weather_evidence 持久化：独立 SQLite（B03/data/weather_evidence.db）。

与本地模拟历史严格分离：
- B02/data/greenmate_b02.db = 本地模拟历史（SIMULATED，30 分钟网格）
- B03/data/weather_evidence.db = 外部真实天气证据（external_api）

成功与失败的证据都入库（失败的 status='error' 同样有审计价值）。
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "weather_evidence.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS weather_evidence (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    location     TEXT NOT NULL,
    provider     TEXT NOT NULL,
    data_source  TEXT NOT NULL DEFAULT 'external_api',
    status       TEXT NOT NULL,            -- success / error
    error_type   TEXT,                     -- error 时的分类
    temperature  REAL,
    humidity     REAL,
    weather_code INTEGER,
    weather_text TEXT,
    wind_speed   REAL,
    retrieved_at TEXT NOT NULL,
    latency_ms   INTEGER,
    evidence_json TEXT NOT NULL            -- 完整 evidence 结构（审计）
);
CREATE INDEX IF NOT EXISTS idx_we_retrieved ON weather_evidence(retrieved_at);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def insert_evidence(conn, evidence):
    w = evidence.get("weather") or {}
    conn.execute(
        "INSERT INTO weather_evidence "
        "(location, provider, data_source, status, error_type, temperature, humidity, "
        " weather_code, weather_text, wind_speed, retrieved_at, latency_ms, evidence_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            evidence.get("query", {}).get("location", ""),
            evidence.get("provider", ""),
            evidence.get("data_source", "external_api"),
            evidence.get("status", "error"),
            (evidence.get("error") or {}).get("error_type"),
            w.get("temperature_c"),
            w.get("humidity_pct"),
            w.get("weather_code"),
            w.get("weather_text"),
            w.get("wind_speed_kph"),
            evidence.get("retrieved_at", ""),
            evidence.get("latency_ms"),
            json.dumps(evidence, ensure_ascii=False),
        ),
    )
    conn.commit()


def list_evidence(conn, limit=20):
    rows = conn.execute(
        "SELECT id, location, provider, data_source, status, error_type, temperature, humidity, "
        "weather_text, retrieved_at, latency_ms FROM weather_evidence "
        "ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def count_evidence(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM weather_evidence").fetchone()["n"]
