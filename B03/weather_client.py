"""B03 天气证据客户端：真实 HTTP 调用外部天气 Web API，返回 weather_evidence。

原则：
- 所有天气数据都来自真实 HTTP 请求，代码中不写死任何天气 JSON；
- weather_evidence 用 data_source="external_api" 区分「外部真实信息」，
  与 B02 的本地模拟历史（SIMULATED，独立 SQLite）严格分离；
- 认证（QWeather 需要 key）、超时、限流(429)、网络异常统一映射为结构化错误，
  失败证据同样生成 weather_evidence（status="error"），绝不伪装成功。

Provider：
- open_meteo（默认）：无需 API Key，真实联网，支持中文地名解析；
- qweather：和风天气，需要 WEATHER_API_KEY（认证流程完整：无 key → config_error，错 key → auth_error）。

测试注入：WEATHER_BASE_URL / WEATHER_GEOCODE_BASE_URL / WEATHER_QWEATHER_BASE_URL
可指向本地测试桩（tests/mock_server.py），用于稳定复现 429 / 超时 / 401。
"""

import json
import os
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
QWEATHER_GEO_URL = "https://geoapi.qweather.com/v2/city/lookup"
QWEATHER_NOW_URL = "https://devapi.qweather.com/v7/weather/now"

# WMO 天气代码 → 中文描述（转换逻辑，不是数据来源）
WMO_TEXT = {
    0: "晴", 1: "基本晴朗", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨", 85: "小阵雪", 86: "大阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}


class WeatherClientError(Exception):
    def __init__(self, error_type, message, http_status=None):
        self.error_type = error_type
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_config():
    """读取配置（每次调用读取，修改 .env 无需重启；测试可注入 base_url）。"""
    load_dotenv()
    provider = os.getenv("WEATHER_PROVIDER", "open_meteo").strip().lower()
    api_key = os.getenv("WEATHER_API_KEY", "").strip()
    try:
        timeout = float(os.getenv("WEATHER_TIMEOUT", "10"))
    except ValueError:
        timeout = 10.0
    language = os.getenv("WEATHER_LANGUAGE", "zh").strip() or "zh"
    cfg = {
        "provider": provider,
        "api_key": api_key,
        "timeout": timeout,
        "language": language,
        "base_url": os.getenv("WEATHER_BASE_URL", "").strip() or None,
        "geocode_base_url": os.getenv("WEATHER_GEOCODE_BASE_URL", "").strip() or None,
        "qweather_base_url": os.getenv("WEATHER_QWEATHER_BASE_URL", "").strip() or None,
    }
    if provider == "qweather" and not api_key:
        raise WeatherClientError(
            "config_error",
            "WEATHER_PROVIDER=qweather 需要配置 WEATHER_API_KEY（和风天气密钥，见 B03/.env.example）")
    if provider not in ("open_meteo", "qweather"):
        raise WeatherClientError(
            "config_error", "不支持的 WEATHER_PROVIDER: %s（可选 open_meteo / qweather）" % provider)
    return cfg


def _looks_like_latlng(location):
    parts = [p.strip() for p in location.split(",")]
    if len(parts) != 2:
        return False
    try:
        return -90 <= float(parts[0]) <= 90 and -180 <= float(parts[1]) <= 180
    except ValueError:
        return False


def fetch_weather(location, language=None, timeout=None):
    """真实 HTTP 调用外部天气 API，返回 weather_evidence 结构（成功/失败都生成证据）。"""
    requested_at = now_str()
    started = time.time()
    location = (location or "").strip()
    try:
        cfg = get_config()
    except WeatherClientError as e:
        return _error_evidence(location, "unknown", requested_at, started, e)

    provider = cfg["provider"]
    query = {"location": location, "language": language or cfg["language"], "requested_at": requested_at}
    try:
        if not location:
            raise WeatherClientError("validation_error", "location 不能为空（如：北京 / 上海 / 39.9,116.4）")
        if provider == "open_meteo":
            payload = _fetch_open_meteo(location, cfg, language, timeout)
        else:
            payload = _fetch_qweather(location, cfg, timeout)
        evidence = {
            "evidence_type": "weather_evidence",
            "data_source": "external_api",  # 外部真实信息，与本地历史/LLM上下文区分
            "provider": provider,
            "query": query,
            "resolved": payload["resolved"],
            "retrieved_at": now_str(),
            "status": "success",
            "weather": payload["weather"],
            "latency_ms": round((time.time() - started) * 1000),
            "raw_response": payload["raw_response"],
            "api_url": payload["api_url"],
        }
        return evidence
    except Exception as e:
        return _error_evidence(location, provider, requested_at, started, e)


def _error_evidence(location, provider, requested_at, started, e):
    """失败证据：status="error" + 结构化 error，记录来源与 retrieved_at。"""
    err = map_error(e)
    return {
        "evidence_type": "weather_evidence",
        "data_source": "external_api",
        "provider": provider,
        "query": {"location": location, "requested_at": requested_at},
        "retrieved_at": now_str(),
        "status": "error",
        "error": err,
        "latency_ms": round((time.time() - started) * 1000),
    }


def map_error(e):
    """异常 → 结构化错误（错误分类稳定，供页面/日志/测试断言使用）。"""
    name = type(e).__name__
    detail = "%s: %s" % (name, str(e)[:200])
    if isinstance(e, WeatherClientError):
        return {"error_type": e.error_type, "message": e.message,
                "http_status": e.http_status, "detail": detail}
    if isinstance(e, httpx.TimeoutException):
        return {"error_type": "timeout", "message": "请求外部天气 API 超时，请稍后重试或调大 WEATHER_TIMEOUT",
                "http_status": None, "detail": detail}
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        mapping = {
            429: ("http_429", "被外部 API 限流（429），请降低请求频率"),
            401: ("auth_error", "认证失败（401）：API Key 无效，请检查 WEATHER_API_KEY"),
            403: ("auth_error", "认证失败（403）：无权限或 Key 被拒绝"),
            404: ("not_found", "API 返回 404：资源不存在"),
        }
        err_type, msg = mapping.get(status, ("api_error", "外部 API 返回错误（HTTP %s）" % status))
        return {"error_type": err_type, "message": msg, "http_status": status, "detail": detail}
    if isinstance(e, httpx.RequestError):
        cause = str(e.__cause__)[:200] if e.__cause__ else str(e)
        return {"error_type": "network_error", "message": "网络异常：无法连接外部天气 API，请检查网络",
                "http_status": None, "detail": "%s: %s" % (name, cause)}
    return {"error_type": "unknown", "message": "天气证据获取失败（%s）" % name,
            "http_status": None, "detail": detail}


# ---------------- Open-Meteo ----------------

def _fetch_open_meteo(location, cfg, language, timeout):
    t = timeout if timeout is not None else cfg["timeout"]
    geo_url = cfg["geocode_base_url"] or GEOCODE_URL
    fc_url = cfg["base_url"] or FORECAST_URL

    # 1. 地点解析（支持 "纬度,经度" 直接使用，支持中文地名）
    if _looks_like_latlng(location):
        lat, lon = [p.strip() for p in location.split(",")]
        name = location
    else:
        r = httpx.get(geo_url, params={
            "name": location, "count": 1, "language": "zh", "format": "json",
        }, timeout=t, follow_redirects=True)
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            raise WeatherClientError("not_found", "未找到地点: %s" % location, http_status=404)
        top = results[0]
        lat, lon = top["latitude"], top["longitude"]
        name = " / ".join(x for x in (top.get("name"), top.get("admin1"), top.get("country")) if x)

    # 2. 当前天气（真实请求，响应字段直接来自 API）
    r2 = httpx.get(fc_url, params={
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "timezone": "auto",
    }, timeout=t, follow_redirects=True)
    r2.raise_for_status()
    body = r2.json()
    cur = body["current"]
    code = cur["weather_code"]
    return {
        "resolved": {"name": name, "latitude": float(lat), "longitude": float(lon)},
        "weather": {
            "temperature_c": cur["temperature_2m"],
            "humidity_pct": cur["relative_humidity_2m"],
            "weather_code": code,
            "weather_text": WMO_TEXT.get(code, "未知(%s)" % code),
            "wind_speed_kph": cur["wind_speed_10m"],
            "local_time": cur.get("time"),
        },
        "raw_response": json.dumps(body, ensure_ascii=False)[:1500],
        "api_url": str(r2.url),
    }


# ---------------- QWeather（需认证，API Key 走环境变量） ----------------

def _fetch_qweather(location, cfg, timeout):
    t = timeout if timeout is not None else cfg["timeout"]
    base = cfg["qweather_base_url"]  # 测试注入；默认 None → 官方域名
    geo_url = (base + "/v2/city/lookup") if base else QWEATHER_GEO_URL
    now_url = (base + "/v7/weather/now") if base else QWEATHER_NOW_URL
    api_key = cfg["api_key"]

    # 1. 城市查询
    r = httpx.get(geo_url, params={"location": location, "key": api_key}, timeout=t)
    body = r.json()
    code = body.get("code")
    if code in ("401", "403") or r.status_code in (401, 403):
        raise WeatherClientError("auth_error", "和风天气认证失败：API Key 无效", http_status=r.status_code or 401)
    if code == "404" or r.status_code == 404:
        raise WeatherClientError("not_found", "未找到地点: %s" % location, http_status=404)
    if code != "200":
        raise WeatherClientError("api_error", "和风天气 API 错误（code=%s）" % code, http_status=r.status_code)
    city = body["location"][0]

    # 2. 实时天气
    r2 = httpx.get(now_url, params={"location": city["id"], "key": api_key}, timeout=t)
    body2 = r2.json()
    code2 = body2.get("code")
    if code2 in ("401", "403") or r2.status_code in (401, 403):
        raise WeatherClientError("auth_error", "和风天气认证失败：API Key 无效", http_status=r2.status_code or 401)
    if code2 != "200":
        raise WeatherClientError("api_error", "和风天气 API 错误（code=%s）" % code2, http_status=r2.status_code)
    now = body2["now"]
    return {
        "resolved": {"name": city.get("name", location), "city_id": city.get("id")},
        "weather": {
            "temperature_c": float(now["temp"]),
            "humidity_pct": float(now["humidity"]),
            "weather_code": now.get("icon"),
            "weather_text": now.get("text"),
            "wind_speed_kph": float(now.get("windSpeed", 0)),
            "local_time": now.get("obsTime"),
        },
        "raw_response": json.dumps(body2, ensure_ascii=False)[:1500],
        "api_url": str(r2.url),
    }
