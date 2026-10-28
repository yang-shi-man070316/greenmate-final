"""S3 天气叠加对照实验测试（无需 LLM Key / 无需联网）。

- B03 fetch_forecast（经注入桩）字段齐全：provider/retrieved_at/forecast_time/status；
- forecast_time 晚于 analysis_time（retrieved_at）校验；
- B05 get_weather_forecast 工具统一返回模板；
- S3 组合判定：baseline stable / with_weather weather_attention 且归因 external_weather；
- 内部基线两轮一致；run_id s3- 格式；记录 roundtrip。

运行：python B07/S3/tests/test_s3.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
S3 = Path(__file__).resolve().parent.parent  # B07/S3
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT, S3):
    sys.path.insert(0, str(d))

from B03 import weather_client  # noqa: E402
from B05.tools import get_weather_forecast  # noqa: E402

from forecast_stub import ForecastStub  # noqa: E402
from judgment import build_judgment  # noqa: E402
from run import (BASELINE_END, BASELINE_START, load_internal_baseline,  # noqa: E402
                 load_run, make_run_id, save_run)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def main():
    results = []

    # 1. 内部基线（两轮一致性基础）
    current, history, prediction = load_internal_baseline()
    samples = history["data"]["samples"]
    results.append(check("内部基线：B02 固定稳态段 7 点（%s~%s）" % (BASELINE_START, BASELINE_END),
                         len(samples) == 7 and samples[0]["timestamp"] == BASELINE_START
                         and samples[-1]["timestamp"] == BASELINE_END,
                         "%d 点" % len(samples)))
    results.append(check("内部基线：温度 29~30℃ 稳态（基线状态无高关注提示）",
                         29.0 <= samples[-1]["temperature"] <= 30.5
                         and max(p["temperature"] for p in samples)
                         - min(p["temperature"] for p in samples) <= 2.0,
                         "末点 %.1f℃" % samples[-1]["temperature"]))
    results.append(check("内部基线：B06 模型输出含 predicted_attention/model_version",
                         prediction["predicted_attention"] in ("NORMAL", "WATCH")
                         and prediction["model_version"] == "b06-rf-v1"))

    # 2. 预报桩 + B03 fetch_forecast + B05 工具
    stub = ForecastStub()
    stub.start()
    saved = os.environ.get("WEATHER_BASE_URL")
    os.environ["WEATHER_BASE_URL"] = stub.base_url
    try:
        ev = weather_client.fetch_forecast("32.06,118.79", hours=6)
    finally:
        if saved is None:
            os.environ.pop("WEATHER_BASE_URL", None)
        else:
            os.environ["WEATHER_BASE_URL"] = saved
        stub.stop()
    results.append(check("B03 fetch_forecast 字段齐全（provider/retrieved_at/forecast_time/status）",
                         all(k in ev for k in ("provider", "retrieved_at", "forecast_time", "status"))
                         and ev["status"] == "success",
                         "provider=%s" % ev["provider"]))
    results.append(check("forecast_time 晚于 analysis_time（retrieved_at）",
                         all(ts.replace("T", " ") > ev["retrieved_at"] for ts in ev["forecast_time"][:1]),
                         "%s > %s" % (ev["forecast_time"][0], ev["retrieved_at"])))

    stub2 = ForecastStub()
    stub2.start()
    saved2 = os.environ.get("WEATHER_BASE_URL")
    os.environ["WEATHER_BASE_URL"] = stub2.base_url
    try:
        tool = get_weather_forecast("32.06,118.79", hours=6)
    finally:
        if saved2 is None:
            os.environ.pop("WEATHER_BASE_URL", None)
        else:
            os.environ["WEATHER_BASE_URL"] = saved2
        stub2.stop()
    results.append(check("B05 get_weather_forecast 统一模板（status/source/provider/retrieved_at）",
                         tool["status"] == "ok" and all(k in tool for k in
                         ("status", "source", "provider", "retrieved_at")),
                         "provider=%s" % tool["provider"]))
    results.append(check("预报内容为阴雨低光照场景（未来3h 降水≥60 或 云量≥80）",
                         any(h["precipitation_probability"] >= 60
                             for h in tool["data"]["forecast"]["hourly"][:3])
                         and any(h["cloud_cover"] >= 80
                                 for h in tool["data"]["forecast"]["hourly"][:3])))

    # 3. S3 组合判定
    j_base = build_judgment(current, history, prediction, None)
    results.append(check("baseline：verdict=stable，无天气风险",
                         j_base["verdict"] == "stable" and j_base["weather_risk"] is None
                         and j_base["attribution"] == "none", j_base["verdict"]))
    j_weather = build_judgment(current, history, prediction, tool)
    results.append(check("with_weather：verdict=weather_attention，归因 external_weather",
                         j_weather["verdict"] == "weather_attention"
                         and j_weather["attribution"] == "external_weather"
                         and j_weather["weather_risk"] is not None,
                         j_weather["verdict"]))
    results.append(check("with_weather：forecast_time_valid=True",
                         j_weather["forecast_time_valid"] is True))
    results.append(check("内部判定两轮一致（internal_verdict 相同）",
                         j_base["internal_verdict"] == j_weather["internal_verdict"],
                         "%s == %s" % (j_base["internal_verdict"], j_weather["internal_verdict"])))

    # 4. run_id 与记录
    rid = make_run_id()
    results.append(check("run_id 为 s3- 前缀 + 时间戳 + 6位uuid", bool(
        __import__("re").match(r"^s3-\d{14}-[0-9a-f]{6}$", rid)), rid))
    record = {"run_id": rid, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "mode": "baseline", "experiment": "S3_baseline",
              "internal_baseline": {"current": current, "history": history, "prediction": prediction},
              "weather_forecast": None, "structured_judgment": j_base,
              "llm_explanation": {"status": "error", "error_type": "test", "message": "无 LLM"}}
    path = save_run(record)
    loaded = load_run(rid)
    results.append(check("记录 save/load roundtrip", loaded["run_id"] == rid
                         and loaded["structured_judgment"]["verdict"] == "stable",
                         str(path)))

    print("\nS3 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
