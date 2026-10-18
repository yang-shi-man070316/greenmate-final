"""异常注入测试桩 HTTP 服务器（仅测试用，业务代码不使用）。

真实 HTTP 请求打到本地桩，用于稳定复现失败场景。
路由与实际客户端请求路径匹配（客户端用 base_url + query 参数发起请求）：
  GET /ok             → 200 正常天气响应（open-meteo forecast 结构，测试桩数据）
  GET /geocode_ok     → 200 地理编码结果
  GET /geocode_empty  → 200 但 results 为空（地点不存在）
  GET /429            → 429 限流
  GET /401            → 401 认证失败
  GET /403            → 403 无权限
  GET /404            → 404
  GET /slow           → sleep 60 后返回（触发客户端超时）
  GET /v2/city/lookup → 401 + body.code=401（和风天气地理编码认证失败）
  GET /v7/weather/now → 200 和风天气实时响应（备用）

说明：桩内响应只是测试数据，业务代码（weather_client.py）不含任何写死的天气 JSON。
用法：python B03/tests/mock_server.py --port 59998
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORECAST_OK = {
    "latitude": 39.9, "longitude": 116.4, "timezone": "Asia/Shanghai",
    "current_units": {"temperature_2m": "°C", "relative_humidity_2m": "%",
                      "weather_code": "wmo code", "wind_speed_10m": "km/h"},
    "current": {"time": "2026-10-16T10:00", "interval": 900,
                "temperature_2m": 12.5, "relative_humidity_2m": 60,
                "weather_code": 2, "wind_speed_10m": 8.8},
}
GEOCODE_OK = {"results": [{"name": "测试市", "latitude": 31.2, "longitude": 121.5,
                          "admin1": "测试省", "country": "测试国"}]}
QWEATHER_OK = {"code": "200", "location": [{"name": "测试市", "id": "101010100"}],
               "now": {"temp": "12", "humidity": "55", "icon": "101", "text": "多云", "windSpeed": "9"}}

ROUTES = {
    "/ok": (200, FORECAST_OK),
    "/geocode_ok": (200, GEOCODE_OK),
    "/geocode_empty": (200, {"results": []}),
    "/429": (429, {"reason": "rate limited"}),
    "/401": (401, {"error": "invalid api key"}),
    "/403": (403, {"error": "no permission"}),
    "/404": (404, {"error": "not found"}),
    "/v2/city/lookup": (401, {"code": "401", "message": "认证失败"}),
    "/v7/weather/now": (200, QWEATHER_OK),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/slow":
            time.sleep(60)  # 让客户端超时
            return
        status, body = ROUTES.get(path, (404, {"error": "unknown route"}))
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # 静默，减少噪音
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=59998)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("mock server on http://127.0.0.1:%d（按 Ctrl+C 停止）" % args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
