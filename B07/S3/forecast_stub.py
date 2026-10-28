"""S3 预报场景桩：线程内 HTTP 服务器，返回「未来 6 小时阴雨低光照」逐小时预报。

- 数据格式对齐 Open-Meteo hourly 响应（precipitation_probability / cloud_cover）；
- 通过 B03 既有注入机制（WEATHER_BASE_URL）生效：B03 fetch_forecast 的真实请求
  打到本桩，请求逻辑/错误处理全部仍由 B03 负责（S3 不写任何天气请求）；
- forecast_time 基于当前时刻的下一个整点起算，保证晚于 analysis_time（retrieved_at）；
- 仅作为 S3 实验场景条件，不修改任何业务代码。
"""

import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 未来 6 小时：高降水概率 + 高云量 → 阴雨低光照
PRECIP = [88, 92, 85, 80, 75, 70]
CLOUD = [95, 93, 90, 88, 85, 80]


def _hourly_times():
    base = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return [(base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(6)]


class ForecastHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {
            "latitude": 32.06, "longitude": 118.79, "timezone": "Asia/Shanghai",
            "hourly_units": {"time": "iso8601", "precipitation_probability": "%",
                             "cloud_cover": "%"},
            "hourly": {
                "time": _hourly_times(),
                "precipitation_probability": PRECIP,
                "cloud_cover": CLOUD,
            },
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # 静默


class ForecastStub:
    """with 上下文管理：启动/停止预报桩，返回注入地址。"""

    def __init__(self, port=59996):
        self.port = port
        self.server = None
        self.thread = None

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.port

    def start(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), ForecastHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.base_url

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server = None
