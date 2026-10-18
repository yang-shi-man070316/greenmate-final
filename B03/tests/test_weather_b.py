"""TestB：查询条件不变，只改非查询参数（timeout），天气数据应保持一致。

真实调用外部天气 API：
  python B03/tests/test_weather_b.py              # 默认 location=北京
  python B03/tests/test_weather_b.py --location 广州

流程：
1. 默认超时（WEATHER_TIMEOUT，10s）查询一次；
2. 只把超时改为 3s（查询条件 location 完全不变）再查询一次；
3. 对比两次 weather 数值：温度/湿度/天气代码/风速应一致（证明结果只依赖查询条件）。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B03 目录

from weather_client import fetch_weather  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="TestB：只改非查询参数")
    parser.add_argument("--location", default="北京")
    args = parser.parse_args()
    loc = args.location

    ev1 = fetch_weather(loc, timeout=10)
    ev2 = fetch_weather(loc, timeout=3)  # 只改 timeout，查询条件不变

    print("第 1 次（timeout=10s）：", _fmt(ev1))
    print("第 2 次（timeout=3s）： ", _fmt(ev2))

    print("-" * 64)
    checks = []
    ok = True
    if ev1["status"] == "success" and ev2["status"] == "success":
        w1, w2 = ev1["weather"], ev2["weather"]
        pairs = [
            ("温度一致", abs(w1["temperature_c"] - w2["temperature_c"]) <= 0.1,
             "%s vs %s" % (w1["temperature_c"], w2["temperature_c"])),
            ("湿度一致", w1["humidity_pct"] == w2["humidity_pct"],
             "%s vs %s" % (w1["humidity_pct"], w2["humidity_pct"])),
            ("天气代码一致", w1["weather_code"] == w2["weather_code"],
             "%s vs %s" % (w1["weather_code"], w2["weather_code"])),
            ("风速一致", abs(w1["wind_speed_kph"] - w2["wind_speed_kph"]) <= 0.1,
             "%s vs %s" % (w1["wind_speed_kph"], w2["wind_speed_kph"])),
            ("查询条件一致（location=%s）" % loc,
             ev1["query"]["location"] == ev2["query"]["location"] == loc, ""),
        ]
        for name, passed, detail in pairs:
            checks.append((name, passed))
            print("  [%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
            ok = ok and passed
    else:
        checks.append(("两次调用均成功", False))
        print("  [FAIL] 两次调用未全部成功（检查网络 / WEATHER_PROVIDER 配置）")
        ok = False
    print("-" * 64)
    print("TestB 结论：%s" % ("通过 ✅（只改参数不改查询条件，天气证据数据一致）" if ok else "未通过 ❌（若两次请求恰逢 API 数据更新，属正常波动，请人工复核）"))
    return 0 if ok else 1


def _fmt(ev):
    if ev["status"] != "success":
        return "失败 [%s] %s" % (ev["error"]["error_type"], ev["error"]["message"])
    w = ev["weather"]
    return "%.1f℃ / %d%% / %s / %.1f km/h（%sms）" % (
        w["temperature_c"], w["humidity_pct"], w["weather_text"], w["wind_speed_kph"], ev["latency_ms"])


if __name__ == "__main__":
    sys.exit(main())
