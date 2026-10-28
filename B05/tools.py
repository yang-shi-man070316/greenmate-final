"""B05 标准工具函数（4 个），统一返回结构：

    {status, source, provider, retrieved_at, data?, error?}

status 语义：
- ok          工具成功执行且有数据
- unavailable 工具功能正常但当前无可用数据（知识库无匹配、历史库为空等）
- error       执行失败（参数非法、外部 API 错误等）

全部工具真实执行：复用 B01（内存状态）、B02（SQLite 历史）、B03（真实天气 API）、
B04（本地知识库）的已有能力，禁止模拟调用。
"""

import time
from datetime import datetime, timedelta

from B02 import db as b02_db
from B03 import weather_client
from B04 import retriever
from states import current_state

# 工具元信息：Agent 注册（LLM 可见的 name/description/parameters）与页面展示共用
TOOL_META = {
    "get_current_environment": {
        "description": "获取 GreenMate 当前环境状态（模拟数据源 SIMULATED）：温度、湿度、光照。无参数。",
        "parameters": {"type": "object", "properties": {}},
    },
    "get_environment_history": {
        "description": "查询最近 N 小时的环境历史数据（30 分钟采样点，SQLite 持久化）。hours 必须为非负数（0 表示最近一个采样点）。",
        "parameters": {"type": "object",
                       "properties": {"hours": {"type": "number", "description": "向前查询的小时数（>=0）"}},
                       "required": ["hours"]},
    },
    "get_weather_evidence": {
        "description": "真实联网查询指定地点的当前天气（外部天气 API），返回带 retrieved_at 的证据结构。",
        "parameters": {"type": "object",
                       "properties": {"location": {"type": "string", "description": "城市名（如 南京）或 纬度,经度"}},
                       "required": ["location"]},
    },
    "get_weather_forecast": {
        "description": "真实联网查询指定地点未来逐小时天气预报（降水概率、云量），返回 forecast_time 与逐小时数据。",
        "parameters": {"type": "object",
                       "properties": {"location": {"type": "string", "description": "城市名或 纬度,经度"},
                                      "hours": {"type": "number", "description": "预报小时数（默认 24）"}},
                       "required": ["location"]},
    },
    "search_tomato_knowledge": {
        "description": "检索本地番茄/绿植养护知识库，返回带 source 引用的 Top-K 知识片段。知识库无匹配内容时返回 unavailable。",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string", "description": "检索关键词或问题，如 高温干燥养护"}},
                       "required": ["query"]},
    },
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _result(status, source, provider, data=None, error=None):
    r = {"status": status, "source": source, "provider": provider, "retrieved_at": _now()}
    if data is not None:
        r["data"] = data
    if error is not None:
        r["error"] = error
    return r


def get_current_environment():
    """获取当前环境状态（SIMULATED，服务端内存，与 B01 同源数据）。"""
    s = current_state()
    return _result("ok", "simulated_state", "greenmate_states", data={
        "state_id": s["state_id"],
        "source_type": s["source_type"],
        "temperature": s["temperature"],
        "temperature_unit": s["temperature_unit"],
        "humidity": s["humidity"],
        "humidity_unit": s["humidity_unit"],
        "light": s["light"],
        "light_unit": s["light_unit"],
    })


def get_environment_history(hours):
    """查询最近 N 小时环境历史（B02 SQLite）。hours 不能为负数。"""
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return _result("error", "simulated_history", "greenmate_b02_db",
                       error={"error_type": "validation_error",
                              "message": "hours 必须是数字（收到: %r）" % hours})
    if hours < 0:
        return _result("error", "simulated_history", "greenmate_b02_db",
                       error={"error_type": "validation_error",
                              "message": "hours 不能为负数（收到: %s）" % hours})

    conn = b02_db.connect()
    try:
        last = b02_db.query_last_timestamp(conn)
        if not last:
            return _result("unavailable", "simulated_history", "greenmate_b02_db",
                           error={"error_type": "no_data", "message": "历史数据库为空，无可用数据"})
        start_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S") - timedelta(hours=hours)
        start_s = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        rows = b02_db.query_series(conn, start_s, last)
        stats = b02_db.query_stats(conn, start_s, last)
    finally:
        conn.close()

    if not rows:
        return _result("unavailable", "simulated_history", "greenmate_b02_db",
                       error={"error_type": "no_data",
                              "message": "最近 %s 小时内没有采样数据" % hours})
    return _result("ok", "simulated_history", "greenmate_b02_db", data={
        "hours": hours,
        "count": len(rows),
        "window_start": rows[0]["timestamp"],
        "window_end": rows[-1]["timestamp"],
        "stats": stats,
        "samples": rows,
    })


def get_weather_evidence(location):
    """真实联网查询地点天气（复用 B03 weather_client，无效地点返回 error）。"""
    location = (location or "").strip()
    if not location:
        return _result("error", "external_api", "weather_api",
                       error={"error_type": "validation_error", "message": "location 不能为空"})
    ev = weather_client.fetch_weather(location)
    if ev["status"] == "success":
        return _result("ok", "external_api", ev["provider"], data={
            "location": ev["query"]["location"],
            "resolved": ev["resolved"],
            "weather": ev["weather"],
            "api_retrieved_at": ev["retrieved_at"],
        })
    return _result("error", "external_api", ev["provider"], error=ev["error"])


def get_weather_forecast(location, hours=24):
    """查询指定地点未来逐小时天气预报（复用 B03 weather_client.fetch_forecast，不重写天气请求）。

    统一返回结构 {status, source, provider, retrieved_at, data?, error?}；
    data 含 forecast_time（应晚于 retrieved_at）与 forecast.hourly（降水概率/云量）。
    """
    location = (location or "").strip()
    if not location:
        return _result("error", "external_api", "weather_api",
                       error={"error_type": "validation_error", "message": "location 不能为空"})
    ev = weather_client.fetch_forecast(location, hours=hours)
    if ev["status"] == "success":
        return _result("ok", "external_api", ev["provider"], data={
            "location": ev["query"]["location"],
            "resolved": ev["resolved"],
            "retrieved_at_api": ev["retrieved_at"],
            "forecast_time": ev["forecast_time"],
            "forecast": ev["forecast"],
        })
    return _result("error", "external_api", ev["provider"], error=ev["error"])


def search_tomato_knowledge(query):
    """检索本地知识库（B04 retriever），返回带 source 引用的 Top-K 片段。"""
    query = (query or "").strip()
    if not query:
        return _result("error", "local_knowledge", "greenmate_b04_kb",
                       error={"error_type": "validation_error", "message": "query 不能为空"})
    segments = retriever.retrieve(query, top_k=3)
    if not segments:
        return _result("unavailable", "local_knowledge", "greenmate_b04_kb",
                       error={"error_type": "no_match",
                              "message": "知识库中没有匹配的内容（未找到相关知识）"})
    return _result("ok", "local_knowledge", "greenmate_b04_kb", data={
        "query": query,
        "count": len(segments),
        "segments": segments,  # 每条含 id/topic/content/source/retrieved_at/score
    })
