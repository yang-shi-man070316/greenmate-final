"""创新点3 天气场景桩：run_agree 用的「升温风险」预报。

- 数据格式对齐 Open-Meteo hourly（含 temperature_2m）；
- 场景：未来 3 小时温度 30.5→32℃ 继续升温（与历史升温、模型 WATCH 方向一致）；
- 通过 B03 既有注入机制（WEATHER_BASE_URL）生效；
- 降温桩复用 B07/S4/weather_stub.CoolingStub（run_conflict）。
"""

import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRECIP = [5, 10, 15, 20, 25, 30]
CLOUD = [30, 40, 50, 60, 70, 75]
TEMPS = [30.5, 31.0, 31.5, 32.0, 32.5, 33.0]  # 未来升温（风险方向）


def _hourly_times():
    base = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return [(base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(6)]


class WarmingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {
            "latitude": 32.06, "longitude": 118.79, "timezone": "Asia/Shanghai",
            "hourly_units": {"time": "iso8601", "precipitation_probability": "%",
                             "cloud_cover": "%", "temperature_2m": "°C"},
            "hourly": {
                "time": _hourly_times(),
                "precipitation_probability": PRECIP,
                "cloud_cover": CLOUD,
                "temperature_2m": TEMPS,
            },
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


class WarmingStub:
    def __init__(self, port=59993):
        self.port = port
        self.server = None
        self.thread = None

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.port

    def start(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), WarmingHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.base_url

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server = None
