"""S4 天气场景桩：返回「未来 6 小时降温」逐小时预报。

- 数据格式对齐 Open-Meteo hourly（precipitation_probability / cloud_cover / temperature_2m）；
- 通过 B03 既有注入机制（WEATHER_BASE_URL）生效，天气请求逻辑全在 B03；
- 场景：未来 3 小时温度 30→27→24℃ 降温、云量下降、无降水——与内部"持续升温"形成分歧
  （提示情况可能缓解/反向变化）；
- 仅作为 S4 实验场景条件。
"""

import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRECIP = [10, 5, 5, 0, 0, 0]
CLOUD = [40, 30, 20, 15, 10, 10]
TEMPS = [30.0, 28.5, 27.0, 25.5, 24.0, 23.0]  # 未来降温


def _hourly_times():
    base = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return [(base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(6)]


class CoolingHandler(BaseHTTPRequestHandler):
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


class CoolingStub:
    def __init__(self, port=59995):
        self.port = port
        self.server = None
        self.thread = None

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.port

    def start(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), CoolingHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.base_url

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server = None
