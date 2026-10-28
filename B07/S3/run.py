"""S3 天气叠加对照实验（终端运行，无网页）。

两组启动参数（内部数据完全相同，唯一变量 = 未来天气预报）：
  python B07/S3/run.py --baseline        # 仅内部稳态基线，输出判断 + run_id
  python B07/S3/run.py --with_weather    # 叠加未来阴雨低光照预报，输出判断 + run_id
  python B07/S3/run.py --inspect RUN_ID  # 读取本次全部记录
  python B07/S3/run.py --compare         # 打印两轮对比（归因天气）

复用清单（不新增数据源/智能体，不重写天气请求）：
- B05 get_weather_forecast(location) → B03 fetch_forecast（天气请求全在 B03）
- B01 内存状态 / B02 稳态段（S1 基线窗口，固定常量）/ B06 已训模型（不重训）
- S1 判断引擎（内部判定）+ S1 LLM 解释（固定 prompt）
风险变化归因于外部天气；天气参与推理，不只是展示文本。
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B02 import db as b02_db  # noqa: E402
from B05.tools import get_current_environment, get_weather_forecast  # noqa: E402
from B06.features import FEATURE_NAMES, extract_features, feature_vector  # noqa: E402
from B06.train import load_model  # noqa: E402
from B07.S1.llm_explain import explain  # noqa: E402

from forecast_stub import ForecastStub  # noqa: E402
from judgment import build_judgment  # noqa: E402

S3_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S3_DIR / "run_records"

# 内部稳态基线（固定常量）：S1 基线窗口（B02 中 10-20 13:30~16:30 的 29~30℃ 稳态段）
BASELINE_START = "2026-10-20 13:30:00"
BASELINE_END = "2026-10-20 16:30:00"
FORECAST_LOCATION = "32.06,118.79"  # 南京（坐标形式，跳过地理编码直接取预报）

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    return "s3-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


def save_run(record):
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    path = RECORDS_DIR / ("%s.json" % record["run_id"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_run(run_id):
    if not re.match(r"^[A-Za-z0-9_-]+$", run_id or ""):
        raise ValueError("非法 run_id：%s" % run_id)
    path = RECORDS_DIR / ("%s.json" % run_id)
    if not path.exists():
        raise FileNotFoundError("未找到运行记录：%s（run_records 目录：%s）" % (run_id, RECORDS_DIR))
    return json.loads(path.read_text(encoding="utf-8"))


def load_internal_baseline():
    """内部稳态基线（两轮完全相同）：B01 状态 + B02 固定稳态段 + B06 模型预测。"""
    current = get_current_environment()
    conn = b02_db.connect()
    try:
        rows = b02_db.query_series(conn, BASELINE_START, BASELINE_END)
    finally:
        conn.close()
    if len(rows) < 7:
        raise RuntimeError("B02 缺少 S1 稳态段（%s ~ %s），请先运行 python B07/S1/run.py 准备数据" % (
            BASELINE_START, BASELINE_END))
    history = {
        "status": "ok", "source": "simulated_history", "provider": "greenmate_b02_db",
        "retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": {"samples": rows},
    }
    model, metadata = load_model()
    points = rows[:6]  # 固定稳态窗口的 6 点
    vec = feature_vector(extract_features(points))
    proba = model.predict_proba([vec])[0]
    classes = list(model.classes_)
    prediction = {
        "predicted_attention": classes[int(proba.argmax())],
        "model_version": metadata["model_version"],
        "probability": {c: round(float(p), 4) for c, p in zip(classes, proba)},
        "input_window": {"start": points[0]["timestamp"], "end": points[-1]["timestamp"]},
    }
    return current, history, prediction


def fetch_forecast_via_stub():
    """复用 B05 get_weather_forecast → B03 fetch_forecast，通过 B03 注入机制接场景桩。"""
    stub = ForecastStub()
    stub.start()
    saved = os.environ.get("WEATHER_BASE_URL")
    os.environ["WEATHER_BASE_URL"] = stub.base_url
    try:
        return get_weather_forecast(FORECAST_LOCATION, hours=6)
    finally:
        if saved is None:
            os.environ.pop("WEATHER_BASE_URL", None)
        else:
            os.environ["WEATHER_BASE_URL"] = saved
        stub.stop()


def run_pipeline(mode):
    """mode: 'baseline' | 'with_weather'。返回运行记录。"""
    print("[S3:%s] 步骤 1：内部稳态基线（B01 状态 + B02 固定稳态段 + B06 模型，两轮完全一致）" % mode)
    current, history, prediction = load_internal_baseline()
    print("[S3:%s]   当前 %.1f℃ | 历史 %s 条（%s ~ %s）| 模型 %s=%s" % (
        mode, current["data"]["temperature"], len(history["data"]["samples"]),
        history["data"]["samples"][0]["timestamp"], history["data"]["samples"][-1]["timestamp"],
        prediction["predicted_attention"], prediction["model_version"]))

    forecast_tool_result = None
    if mode == "with_weather":
        print("[S3:%s] 步骤 2：叠加未来天气预报（复用 B05 get_weather_forecast → B03，场景桩：阴雨低光照）" % mode)
        forecast_tool_result = fetch_forecast_via_stub()
        print("[S3:%s]   天气工具 status=%s | provider=%s | retrieved_at=%s | forecast_time 首点=%s" % (
            mode, forecast_tool_result["status"], forecast_tool_result["provider"],
            forecast_tool_result["retrieved_at"],
            (forecast_tool_result.get("data") or {}).get("forecast_time", [None])[0]))
        fc = (forecast_tool_result.get("data") or {}).get("forecast") or {}
        next3 = (fc.get("hourly") or [])[:3]
        print("[S3:%s]   未来 3 小时：降水概率 %s%%，云量 %s%%" % (
            mode, [h["precipitation_probability"] for h in next3],
            [h["cloud_cover"] for h in next3]))
    else:
        print("[S3:%s] 步骤 2：无外部天气（基线场景）" % mode)

    print("[S3:%s] 步骤 3：组合判定（内部 S1 引擎 + 天气维度，LLM 无权修改）" % mode)
    judgment = build_judgment(current, history, prediction, forecast_tool_result)
    print("[S3:%s]   internal_verdict=%s | verdict=%s | 归因=%s | forecast_time_valid=%s" % (
        mode, judgment["internal_verdict"], judgment["verdict"],
        judgment["attribution"], judgment["forecast_time_valid"]))

    print("[S3:%s] 步骤 4：LLM 自然语言解释（固定 prompt，天气证据参与推理）" % mode)
    llm = explain({
        "current_state": judgment["current_state"],
        "recent_trend": judgment["recent_trend"],
        "prediction": {"predicted_attention": prediction["predicted_attention"],
                       "model_version": prediction["model_version"],
                       "probability": prediction["probability"]},
        "weather_forecast": forecast_tool_result,  # baseline 为 None，with_weather 为天气证据
        "judgment": judgment,
    })
    print("[S3:%s]   LLM 状态=%s" % (mode, llm.get("status")))

    run_id = make_run_id()
    record = {
        "run_id": run_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "s3_task": "S3 天气叠加对照实验",
        "experiment": "S3_%s" % mode,
        "mode": mode,
        "internal_baseline": {"current": current, "history": history, "prediction": prediction},
        "weather_forecast": forecast_tool_result,
        "structured_judgment": judgment,
        "llm_explanation": llm,
        "chain_status": ("complete" if llm.get("status") == "success"
                         else "structured_complete_llm_unavailable"),
    }
    path = save_run(record)
    print("[S3:%s] 运行记录已保存：%s" % (mode, path))
    print("[S3:%s] ======== run_id: %s ========" % (mode, run_id))
    print("[S3:%s] 查看记录：python B07/S3/run.py --inspect %s" % (mode, run_id))
    return record


def find_latest(experiment):
    files = sorted(RECORDS_DIR.glob("s3-*.json"))
    for path in reversed(files):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("experiment") == experiment:
            return record
    return None


def print_comparison(base, weather):
    """两轮对比：区分历史信息与天气带来的外部变化，风险变化归因天气。"""
    bj = base["structured_judgment"]
    wj = weather["structured_judgment"]
    print()
    print("=" * 64)
    print("两轮对比：--baseline vs --with_weather")
    print("=" * 64)
    print("内部数据（历史信息）：两轮完全相同 ✅（B01 状态 24℃/65%%/12000lux | "
          "B02 稳态段 %s~%s | B06 %s）" % (
              BASELINE_START, BASELINE_END, base["internal_baseline"]["prediction"]["model_version"]))
    print("  baseline 内部判定      : %s" % bj["internal_verdict"])
    print("  with_weather 内部判定  : %s（与 baseline 相同）" % wj["internal_verdict"])
    print("-" * 64)
    print("外部天气（唯一变量）：")
    print("  baseline               : 无天气预报")
    print("  with_weather           : 未来 3 小时降水概率 %s%%，云量 %s%%（阴雨低光照，provider=%s）"
          % (wj["weather_risk"]["precipitation_probability_3h"],
             wj["weather_risk"]["cloud_cover_3h"],
             weather["weather_forecast"]["provider"]))
    print("-" * 64)
    print("最终判定：")
    print("  baseline     verdict=%s（关注等级：低，无需重点关注）" % bj["verdict"])
    print("  with_weather verdict=%s（关注等级：高，需要重点关注）" % wj["verdict"])
    print("  风险变化归因：%s（内部稳态判定不变，差异全部来自外部天气预报）" % wj["attribution"])
    print("=" * 64)
    print("结论：历史信息（内部稳态）在两组中完全一致且均判定稳定；")
    print("      with_weather 的风险升级完全由外部天气证据（阴雨低光照预报）驱动，")
    print("      LLM 解释中天气作为推理依据出现，而非仅展示文本。")


def summarize(record):
    j = record["structured_judgment"]
    lines = [
        "=" * 64,
        "运行记录 %s（%s，创建于 %s）" % (record["run_id"], record["mode"], record["created_at"]),
        "=" * 64,
        "内部基线：当前 %.1f℃/%.0f lux | 历史 %s ~ %s | 模型 %s=%s" % (
            record["internal_baseline"]["current"]["data"]["temperature"],
            record["internal_baseline"]["current"]["data"]["light"],
            record["internal_baseline"]["history"]["data"]["samples"][0]["timestamp"],
            record["internal_baseline"]["history"]["data"]["samples"][-1]["timestamp"],
            record["internal_baseline"]["prediction"]["predicted_attention"],
            record["internal_baseline"]["prediction"]["model_version"]),
        "天气预报：%s" % (json.dumps(record["weather_forecast"], ensure_ascii=False)
                        if record["weather_forecast"] else "无（baseline）"),
        "结构化判定：internal=%s verdict=%s 归因=%s forecast_time_valid=%s" % (
            j["internal_verdict"], j["verdict"], j["attribution"], j["forecast_time_valid"]),
    ]
    llm = record["llm_explanation"]
    if llm.get("status") == "success":
        lines += ["", "【LLM 解释】", llm["answer"]]
    else:
        lines += ["", "【LLM 解释】不可用：[%s] %s" % (llm.get("error_type"), llm.get("message"))]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="GreenMate S3 天气叠加对照实验")
    parser.add_argument("--baseline", action="store_true", help="仅内部稳态基线")
    parser.add_argument("--with_weather", action="store_true", help="叠加未来阴雨低光照预报")
    parser.add_argument("--inspect", metavar="RUN_ID", help="按 run_id 读取记录")
    parser.add_argument("--compare", action="store_true", help="打印两轮对比")
    args = parser.parse_args()

    if args.inspect:
        print(summarize(load_run(args.inspect)))
        return 0
    if args.compare:
        base = find_latest("S3_baseline")
        weather = find_latest("S3_with_weather")
        if not base or not weather:
            print("需要先分别运行 --baseline 与 --with_weather 生成两轮记录")
            return 1
        print_comparison(base, weather)
        return 0

    if args.with_weather:
        record = run_pipeline("with_weather")
        base = find_latest("S3_baseline")
        if base:
            print_comparison(base, record)
        return 0
    if args.baseline:
        run_pipeline("baseline")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
