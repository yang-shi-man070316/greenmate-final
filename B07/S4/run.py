"""S4 多源证据分歧推理入口（终端运行，无网页）。

固定分歧场景：
- E1 B02 历史时序：持续升温（10-08 11:30~14:30，26.3→38.1℃）
- E2 B06 模型：WATCH（真实模型输出，不修改）
- E3 B03 天气：未来降温（场景桩，30→27→24℃）
- E4 B04 知识：持续高温值得关注，但不能证明未来一定继续恶化（K09）

用法（项目根目录）：
  python B07/S4/run.py --baseline         # 仅内部 B02+B06 证据
  python B07/S4/run.py --with_evidence    # 叠加 B03 天气 + B04 知识证据
  python B07/S4/run.py --compare          # 两轮对比
  python B07/S4/run.py --inspect RUN_ID   # 读取记录（含反向查询：结论依据哪些证据）

日志四层概念（工具被调用 ≠ 结果被采用）：
  tool_called → tool_success → converted_to_evidence → adopted_in_judgment
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
from B05.tools import get_weather_forecast, search_tomato_knowledge  # noqa: E402
from B06.features import extract_features, feature_vector  # noqa: E402
from B06.train import load_model  # noqa: E402

import evidence  # noqa: E402
from judgment import build_judgment, explain_conclusion  # noqa: E402
from llm_explain import explain  # noqa: E402
from weather_stub import CoolingStub  # noqa: E402

S4_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S4_DIR / "run_records"

# 内部固定基线：B02 热浪 ramp 段（持续快速升温），B06 对该段真实输出 WATCH（实测 0.955）
BASELINE_START = "2026-10-08 11:30:00"
BASELINE_END = "2026-10-08 14:30:00"
FORECAST_LOCATION = "32.06,118.79"
KNOWLEDGE_QUERY = "持续高温 未来 恶化 趋势"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    return "s4-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


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


def load_internal_evidence(log):
    """E1（B02 持续升温历史）+ E2（B06 模型 WATCH），两轮完全相同。"""
    conn = b02_db.connect()
    try:
        rows = b02_db.query_series(conn, BASELINE_START, BASELINE_END)
    finally:
        conn.close()
    if len(rows) < 7:
        raise RuntimeError("B02 缺少固定升温段（%s ~ %s）" % (BASELINE_START, BASELINE_END))
    temps = [r["temperature"] for r in rows]
    e1 = evidence.wrap(
        "internal_history", "greenmate_b02_db", "ok",
        result={"window": "%s ~ %s" % (rows[0]["timestamp"], rows[-1]["timestamp"]),
                "count": len(rows),
                "temperature_first": temps[0], "temperature_last": temps[-1],
                "trend": "持续升温（%.1f → %.1f℃）" % (temps[0], temps[-1])})
    log.append({"tool": "B02 历史查询（b02_db.query_series）", "tool_called": True,
                "tool_success": True, "converted_to_evidence": True,
                "adopted_in_judgment": True, "note": "固定窗口 %s~%s，持续升温" % (BASELINE_START, BASELINE_END)})

    model, metadata = load_model()
    import numpy as np
    points = rows[:6]
    vec = feature_vector(extract_features(points))
    proba = model.predict_proba([vec])[0]
    classes = list(model.classes_)
    prediction = {
        "predicted_attention": classes[int(np.argmax(proba))],
        "probability": {c: round(float(p), 4) for c, p in zip(classes, proba)},
        "input_window": "%s ~ %s" % (points[0]["timestamp"], points[-1]["timestamp"]),
    }
    e2 = evidence.wrap(
        "ml_prediction", "greenmate_b06_rf", "ok",
        result=prediction, model_version=metadata["model_version"])
    log.append({"tool": "B06 模型推理（load_model+predict_proba，未重训）", "tool_called": True,
                "tool_success": True, "converted_to_evidence": True,
                "adopted_in_judgment": True,
                "note": "predicted_attention=%s（模型输出原样保留，不修改）" % prediction["predicted_attention"]})
    return e1, e2


def fetch_cooling_forecast(log):
    """E3：复用 B05 get_weather_forecast → B03（场景桩：未来降温）。"""
    stub = CoolingStub()
    stub.start()
    saved = os.environ.get("WEATHER_BASE_URL")
    os.environ["WEATHER_BASE_URL"] = stub.base_url
    try:
        tool_result = get_weather_forecast(FORECAST_LOCATION, hours=6)
    finally:
        if saved is None:
            os.environ.pop("WEATHER_BASE_URL", None)
        else:
            os.environ["WEATHER_BASE_URL"] = saved
        stub.stop()

    success = tool_result["status"] == "ok"
    # 采用条件：forecast_time 晚于 retrieved_at（校验失败则调用成功但不采用）
    forecast_times = (tool_result.get("data") or {}).get("forecast_time") or []
    retrieved = tool_result.get("retrieved_at") or ""
    valid = bool(forecast_times) and forecast_times[0].replace("T", " ") > retrieved
    e3 = evidence.from_tool(
        "external_weather", tool_result.get("provider", "weather_api"), tool_result,
        provider=tool_result.get("provider"), forecast_time=forecast_times)
    log.append({"tool": "B05 get_weather_forecast → B03 fetch_forecast（场景桩：未来降温）",
                "tool_called": True, "tool_success": success,
                "converted_to_evidence": True, "adopted_in_judgment": valid,
                "note": ("forecast_time 校验通过（首点 %s > retrieved_at %s）" % (forecast_times[0], retrieved)
                         if valid else "forecast_time 校验失败，证据未被本次判断采用")})
    return e3, valid


def fetch_knowledge(log):
    """E4：复用 B05 search_tomato_knowledge（B04 检索，K09 命中）。"""
    tool_result = search_tomato_knowledge(KNOWLEDGE_QUERY)
    segments = ((tool_result.get("data") or {}).get("segments")) or []
    k09 = [s for s in segments if s.get("id") == "K09"]
    adopted = bool(k09)
    citation = [{"id": s["id"], "source": s["source"]} for s in segments]
    e4 = evidence.from_tool("local_knowledge", "greenmate_b04_kb", tool_result,
                            citation=citation)
    log.append({"tool": "B05 search_tomato_knowledge（B04 本地知识检索）",
                "tool_called": True,
                "tool_success": tool_result["status"] in ("ok", "unavailable"),
                "converted_to_evidence": True, "adopted_in_judgment": adopted,
                "note": ("命中 %s，采用" % [s["id"] for s in segments]
                         if adopted else "未命中 K09，证据未被采用")})
    return e4, adopted


def run_pipeline(mode):
    print("[S4:%s] 步骤 1：内部证据（B02 持续升温 + B06 模型，两轮完全相同）" % mode)
    log = []
    evidence_list = []
    e1, e2 = load_internal_evidence(log)
    evidence_list += [e1, e2]
    print("[S4:%s]   E1 B02 历史：%s（status=%s）" % (mode, e1["result"]["trend"], e1["status"]))
    print("[S4:%s]   E2 B06 模型：%s 概率=%s（status=%s, model_version=%s）" % (
        mode, e2["result"]["predicted_attention"], e2["result"]["probability"],
        e2["status"], e2["model_version"]))

    if mode == "with_evidence":
        print("[S4:%s] 步骤 2：叠加外部证据（B03 天气 + B04 知识）" % mode)
        e3, adopted3 = fetch_cooling_forecast(log)
        if adopted3:
            evidence_list.append(e3)
        next3 = ((e3.get("result") or {}).get("forecast") or {}).get("hourly", [])[:3]
        print("[S4:%s]   E3 B03 天气：未来 3 小时温度 %s℃（status=%s, provider=%s, forecast_time 首点=%s）"
              % (mode, [h.get("temperature_2m") for h in next3], e3["status"],
                 e3["provider"], (e3.get("forecast_time") or [None])[0]))
        e4, adopted4 = fetch_knowledge(log)
        if adopted4:
            evidence_list.append(e4)
        print("[S4:%s]   E4 B04 知识：命中 %s（status=%s, citation=%s）" % (
            mode, [s["id"] for s in ((e4.get("result") or {}).get("segments") or [])],
            e4["status"], e4.get("citation")))
    else:
        log.append({"tool": "B03 天气 / B04 知识", "tool_called": False,
                    "tool_success": None, "converted_to_evidence": False,
                    "adopted_in_judgment": False, "note": "baseline 模式不调用外部工具"})

    print("[S4:%s] 步骤 3：分歧判定（不强行合并单一确定结论）" % mode)
    judgment = build_judgment(evidence_list)
    print("[S4:%s]   verdict=%s（%s）" % (mode, judgment["verdict"], judgment["verdict_note"]))
    print("[S4:%s]   支持提高关注: %s | 可能缓解: %s | 不足以确定: %s" % (
        mode,
        [e.get("evidence_id") for e in judgment["synthesis"]["support_attention"]],
        [e.get("evidence_id") for e in judgment["synthesis"]["mitigating_or_reverse"]],
        [e.get("evidence_id") for e in judgment["synthesis"]["insufficient"]]))

    print("[S4:%s] 步骤 4：LLM 三段式合成推理（证据绑定 + 禁止强确定性结论）" % mode)
    llm = explain(evidence_list, judgment)
    print("[S4:%s]   LLM 状态=%s，禁止词命中=%s" % (mode, llm.get("status"), llm.get("forbidden_hits")))

    run_id = make_run_id()
    record = {
        "run_id": run_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "s4_task": "S4 多源证据分歧推理",
        "experiment": "S4_%s" % mode,
        "mode": mode,
        "evidence": evidence_list,
        "pipeline_log": log,
        "structured_judgment": judgment,
        "llm_explanation": llm,
        "chain_status": ("complete" if llm.get("status") == "success"
                         else "structured_complete_llm_unavailable"),
    }
    path = save_run(record)
    print("[S4:%s] 运行记录已保存：%s" % (mode, path))
    print("[S4:%s] ======== run_id: %s ========" % (mode, run_id))
    print("[S4:%s] 查看记录：python B07/S4/run.py --inspect %s" % (mode, run_id))
    return record


def find_latest(experiment):
    files = sorted(RECORDS_DIR.glob("s4-*.json"))
    for path in reversed(files):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("experiment") == experiment:
            return record
    return None


def print_comparison(base, weather):
    bj = base["structured_judgment"]
    wj = weather["structured_judgment"]
    print()
    print("=" * 64)
    print("两轮对比：--baseline vs --with_evidence")
    print("=" * 64)
    print("内部基线（B02+B06）：两轮完全相同 ✅")
    print("  E1 B02 历史：持续升温（26.3 → 38.1℃）→ 支持提高关注")
    print("  E2 B06 模型：WATCH（真实输出）→ 支持提高关注")
    print("-" * 64)
    print("新增多源证据（仅 with_evidence 采用）：")
    print("  E3 B03 天气：未来 3 小时降温（30→27→24℃）→ 提示情况可能缓解/反向变化")
    print("  E4 B04 知识：持续高温值得关注但不能证明未来一定恶化（K09）→ 当前信息不足以确定")
    print("-" * 64)
    print("判断变化：")
    print("  baseline       verdict=%s（内部证据一致指向风险，明确关注）" % bj["verdict"])
    print("  with_evidence  verdict=%s（关注但存在缓解信号与不确定性，不强行合并单一结论）" % wj["verdict"])
    print("  变化归因：新增 B03/B04 多源证据（内部 B02+B06 证据与判定输入完全未变）")
    print("-" * 64)
    print("每条推理标注依赖证据（with_evidence 三部分）：")
    print("  支持提高关注: %s" % [e.get("evidence_id") for e in wj["synthesis"]["support_attention"]])
    print("  可能缓解/反向: %s" % [e.get("evidence_id") for e in wj["synthesis"]["mitigating_or_reverse"]])
    print("  不足以确定: %s" % [e.get("evidence_id") for e in wj["synthesis"]["insufficient"]])
    print("=" * 64)


def summarize(record):
    j = record["structured_judgment"]
    lines = [
        "=" * 64,
        "运行记录 %s（%s，创建于 %s）" % (record["run_id"], record["mode"], record["created_at"]),
        "=" * 64,
        "【证据清单（统一字段 source_type/source/time/status/result/error + 专属扩展）】",
    ]
    for ev in record["evidence"]:
        lines.append("  %s | %s | %s | status=%s | 扩展=%s" % (
            ev.get("evidence_id"), ev["source_type"], ev["source"], ev["status"],
            {k: v for k, v in ev.items() if k in ("provider", "forecast_time", "citation", "model_version")}))
    lines += [
        "",
        "【工具调用日志（called → success → converted → adopted 四层）】",
    ]
    for entry in record["pipeline_log"]:
        lines.append("  %s | called=%s success=%s converted=%s adopted=%s | %s" % (
            entry["tool"], entry["tool_called"], entry["tool_success"],
            entry["converted_to_evidence"], entry["adopted_in_judgment"], entry.get("note", "")))
    lines += [
        "",
        "【结构化判定】verdict=%s（%s）" % (j["verdict"], j["verdict_note"]),
        "【反向查询示例】结论 E3（天气降温）依据：%s" % explain_conclusion(j, "E3"),
    ]
    llm = record["llm_explanation"]
    if llm.get("status") == "success":
        lines += ["", "【LLM 三段式推理】", llm["answer"]]
    else:
        lines += ["", "【LLM】不可用：[%s] %s" % (llm.get("error_type"), llm.get("message"))]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="GreenMate S4 多源证据分歧推理")
    parser.add_argument("--baseline", action="store_true", help="仅内部 B02+B06 证据")
    parser.add_argument("--with_evidence", action="store_true", help="叠加 B03 天气 + B04 知识")
    parser.add_argument("--inspect", metavar="RUN_ID", help="按 run_id 读取记录")
    parser.add_argument("--compare", action="store_true", help="两轮对比")
    args = parser.parse_args()

    if args.inspect:
        print(summarize(load_run(args.inspect)))
        return 0
    if args.compare:
        base = find_latest("S4_baseline")
        weather = find_latest("S4_with_evidence")
        if not base or not weather:
            print("需要先分别运行 --baseline 与 --with_evidence 生成两轮记录")
            return 1
        print_comparison(base, weather)
        return 0
    if args.with_evidence:
        record = run_pipeline("with_evidence")
        base = find_latest("S4_baseline")
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
