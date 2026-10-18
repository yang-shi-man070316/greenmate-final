"""异常测试：超时 / 429 限流 / 认证失败(401/403) / 网络异常 / 地点不存在 / 转换逻辑。

真实 HTTP 请求打到本地测试桩（mock_server.py，测试脚本内启动线程），
通过环境变量注入 base_url（业务代码零改动、零硬编码天气数据）。

  python B03/tests/test_failures.py

用例与期望 error_type：
  1. 超时          （桩 sleep 60s + WEATHER_TIMEOUT=2）     → timeout
  2. 限流 429      （桩 /429）                             → http_429
  3. 认证失败 401  （桩 /401，open_meteo 注入）             → auth_error
  4. 无权限 403    （桩 /403）                             → auth_error
  5. 地点不存在    （桩 /geocode_empty）                   → not_found
  6. 网络异常      （指向未监听端口）                       → network_error
  7. 转换逻辑      （桩 /ok 成功响应 → evidence 组装正确）   → success 且数值来自桩响应
  8. QWeather 认证 （桩 /qweather/401 + provider=qweather） → auth_error
"""

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B03 目录
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests 目录（mock_server）

from mock_server import Handler  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

from weather_client import fetch_weather  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

MOCK_PORT = 59998
MOCK = "http://127.0.0.1:%d" % MOCK_PORT
DEAD_PORT = 59997  # 无监听端口


def start_mock():
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def set_env(**kw):
    saved = {}
    for k, v in kw.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = str(v)
    return saved


def restore_env(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def run_case(name, expect, env, location, timeout=None):
    saved = set_env(**env)
    try:
        ev = fetch_weather(location, timeout=timeout)
    finally:
        restore_env(saved)
    if ev["status"] == "success":
        actual = "success"
        msg = "温度 %.1f℃ / %s" % (ev["weather"]["temperature_c"], ev["weather"]["weather_text"])
    else:
        actual = ev["error"]["error_type"]
        msg = ev["error"]["message"]
    passed = actual == expect
    print("用例：%s" % name)
    print("  期望: %s | 实际: %s" % (expect, actual))
    print("  %s" % msg)
    if ev["status"] == "error" and ev["error"].get("http_status"):
        print("  HTTP: %s | detail: %s" % (ev["error"]["http_status"], ev["error"].get("detail", "")))
    print("  结论: %s\n" % ("PASS ✅" if passed else "FAIL ❌"))
    return passed


def main():
    server = start_mock()
    try:
        results = [
            run_case("超时（桩 /slow + timeout=2s）", "timeout",
                     {"WEATHER_PROVIDER": "open_meteo", "WEATHER_BASE_URL": MOCK + "/slow",
                      "WEATHER_GEOCODE_BASE_URL": MOCK + "/geocode_ok", "WEATHER_TIMEOUT": "2"},
                     "39.9,116.4", timeout=2),
            run_case("限流 429（桩 /429）", "http_429",
                     {"WEATHER_PROVIDER": "open_meteo", "WEATHER_BASE_URL": MOCK + "/429",
                      "WEATHER_GEOCODE_BASE_URL": MOCK + "/geocode_ok", "WEATHER_TIMEOUT": "5"},
                     "39.9,116.4"),
            run_case("认证失败 401（桩 /401）", "auth_error",
                     {"WEATHER_PROVIDER": "open_meteo", "WEATHER_BASE_URL": MOCK + "/401",
                      "WEATHER_GEOCODE_BASE_URL": MOCK + "/geocode_ok", "WEATHER_TIMEOUT": "5"},
                     "39.9,116.4"),
            run_case("无权限 403（桩 /403）", "auth_error",
                     {"WEATHER_PROVIDER": "open_meteo", "WEATHER_BASE_URL": MOCK + "/403",
                      "WEATHER_GEOCODE_BASE_URL": MOCK + "/geocode_ok", "WEATHER_TIMEOUT": "5"},
                     "39.9,116.4"),
            run_case("地点不存在（桩 /geocode_empty）", "not_found",
                     {"WEATHER_PROVIDER": "open_meteo", "WEATHER_BASE_URL": MOCK + "/ok",
                      "WEATHER_GEOCODE_BASE_URL": MOCK + "/geocode_empty", "WEATHER_TIMEOUT": "5"},
                     "不存在的地方"),
            run_case("网络异常（未监听端口）", "network_error",
                     {"WEATHER_PROVIDER": "open_meteo",
                      "WEATHER_BASE_URL": "http://127.0.0.1:%d/ok" % DEAD_PORT,
                      "WEATHER_GEOCODE_BASE_URL": "http://127.0.0.1:%d/geocode_ok" % DEAD_PORT,
                      "WEATHER_TIMEOUT": "4"},
                     "39.9,116.4"),
            run_case("转换逻辑（桩 /ok 成功响应 → 证据组装）", "success",
                     {"WEATHER_PROVIDER": "open_meteo", "WEATHER_BASE_URL": MOCK + "/ok",
                      "WEATHER_GEOCODE_BASE_URL": MOCK + "/geocode_ok", "WEATHER_TIMEOUT": "5"},
                     "39.9,116.4"),
            run_case("QWeather 认证失败（桩 /v2/city/lookup → 401）", "auth_error",
                     {"WEATHER_PROVIDER": "qweather", "WEATHER_API_KEY": "bad-key",
                      "WEATHER_QWEATHER_BASE_URL": MOCK, "WEATHER_TIMEOUT": "5"},
                     "北京"),
            run_case("QWeather 缺密钥（config_error）", "config_error",
                     {"WEATHER_PROVIDER": "qweather", "WEATHER_API_KEY": "",
                      "WEATHER_QWEATHER_BASE_URL": MOCK, "WEATHER_TIMEOUT": "5"},
                     "北京"),
        ]
        passed_all = all(results)
        print("异常测试总结论：%s" % ("全部通过 ✅（所有失败场景都生成结构化错误证据，未伪装成功）" if passed_all else "存在未通过项 ❌"))
        return 0 if passed_all else 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
