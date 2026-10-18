"""TestA：改变查询条件（location），weather_evidence 应随之变化。

真实调用外部天气 API（不经过 FastAPI，直连 weather_client）：
  python B03/tests/test_weather_a.py                # 默认对比 北京 / 上海
  python B03/tests/test_weather_a.py --locations 北京 上海 广州

断言：
- 每个地点都拿到 success 证据（真实 HTTP，绝不使用写死 JSON）；
- 解析出的地点（resolved）随查询条件不同而不同；
- 温度/湿度数值落在合理范围（数据来自真实响应）。
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # 项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B03 目录

from weather_client import fetch_weather  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="TestA：改变查询条件")
    parser.add_argument("--locations", nargs="+", default=["北京", "上海"])
    args = parser.parse_args()

    results = []
    for loc in args.locations:
        ev = fetch_weather(loc)
        results.append((loc, ev))
        if ev["status"] == "success":
            print("location=%s → 解析: %s | 温度 %.1f℃ | 湿度 %d%% | %s | 风速 %.1f km/h | %sms" % (
                loc, ev["resolved"]["name"], ev["weather"]["temperature_c"],
                ev["weather"]["humidity_pct"], ev["weather"]["weather_text"],
                ev["weather"]["wind_speed_kph"], ev["latency_ms"]))
        else:
            print("location=%s → 失败: [%s] %s" % (loc, ev["error"]["error_type"], ev["error"]["message"]))

    print("-" * 64)
    checks = []
    ok = True
    for loc, ev in results:
        checks.append(("location=%s 成功获取证据" % loc, ev["status"] == "success"))
    resolved = [ev.get("resolved", {}).get("name") for _, ev in results if ev["status"] == "success"]
    if len(set(resolved)) >= 2:
        checks.append(("解析地点随查询条件变化（%s）" % " ≠ ".join(map(str, resolved)), True))
    else:
        checks.append(("解析地点随查询条件变化", False))
    for loc, ev in results:
        if ev["status"] == "success":
            w = ev["weather"]
            checks.append(("location=%s 数值在合理范围（温度 %.1f∈[-50,60], 湿度 %d∈[0,100]）" % (
                loc, w["temperature_c"], w["humidity_pct"]),
                -50 <= w["temperature_c"] <= 60 and 0 <= w["humidity_pct"] <= 100))
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("-" * 64)
    print("TestA 结论：%s" % ("通过 ✅（改变查询条件，证据随真实返回变化）" if ok else "未通过 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
