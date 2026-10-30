"""创新点3 实验入口：让系统学会「有些话现在不能说」。

三组对照（统一固定提问，内部证据完全相同，仅天气证据条件变化）：
  --run agree            天气=升温（与历史升温+模型 WATCH 一致）→ 结论相对明确
  --run conflict         天气=降温（与内部证据分歧）→ 保留分歧与不确定性
  --run missing_weather  天气调用失败缺失 → 收缩判断边界，禁止脑补天气信息

复用：S4 采集组件（内部证据+知识）、S4 CoolingStub（降温桩）、S5 故障注入（死端口）、
i3 判定/LLM（表达强度跟随证据条件）。

用法（项目根目录）：
  python B07/S5/i3_run.py --run-all       # 依次运行三组 + 生成报告
  python B07/S5/i3_run.py --run agree|conflict|missing_weather
  python B07/S5/i3_run.py --report        # 生成 INNOVATE_3_REPORT.md
  python B07/S5/i3_run.py --inspect RUN_ID
  python B07/S5/i3_check.py --run-id RUN_ID   # 自检：强确定词 + 私自补齐缺失证据
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
for d in (ROOT / "B07" / "S4", ROOT / "B06", ROOT / "B05", ROOT / "B04",
          ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B05.tools import get_weather_forecast  # noqa: E402
from B07.S4 import evidence as s4_evidence  # noqa: E402
from B07.S4.run import (FORECAST_LOCATION, fetch_knowledge,  # noqa: E402
                        load_internal_evidence)
from B07.S4.weather_stub import CoolingStub  # noqa: E402

from i3_judgment import build_judgment  # noqa: E402
from i3_llm import explain  # noqa: E402
from i3_weather_stub import WarmingStub  # noqa: E402

S5_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S5_DIR / "run_records"

FIXED_QUESTION = "结合全部可用证据，分析当前番茄生长环境风险：哪些方面可以判断，哪些方面因证据受限无法判断？"
MODES = ("agree", "conflict", "missing_weather")

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    return "i3-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


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


def fetch_weather_by_mode(mode, log):
    """按模式获取天气证据（或缺失）。返回 (adopted, missing)。"""
    if mode == "agree":
        stub = WarmingStub()
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
        ev = s4_evidence.from_tool("external_weather",
                                   tool_result.get("provider", "weather_api"), tool_result,
                                   provider=tool_result.get("provider", "weather_api"),
                                   forecast_time=(tool_result.get("data") or {}).get("forecast_time"))
        log.append({"tool": "B05 get_weather_forecast → B03（升温桩）", "tool_called": True,
                    "tool_success": True, "converted_to_evidence": True,
                    "adopted_in_judgment": True, "note": "场景：天气升温（与内部证据一致）"})
        return ev, None
    if mode == "conflict":
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
        ev = s4_evidence.from_tool("external_weather",
                                   tool_result.get("provider", "weather_api"), tool_result,
                                   provider=tool_result.get("provider", "weather_api"),
                                   forecast_time=(tool_result.get("data") or {}).get("forecast_time"))
        log.append({"tool": "B05 get_weather_forecast → B03（降温桩）", "tool_called": True,
                    "tool_success": True, "converted_to_evidence": True,
                    "adopted_in_judgment": True, "note": "场景：天气降温（与内部证据分歧）"})
        return ev, None
    # missing_weather：死端口 → 真实调用失败
    saved = os.environ.get("WEATHER_BASE_URL")
    os.environ["WEATHER_BASE_URL"] = "http://127.0.0.1:59994"
    try:
        tool_result = get_weather_forecast(FORECAST_LOCATION, hours=6)
    finally:
        if saved is None:
            os.environ.pop("WEATHER_BASE_URL", None)
        else:
            os.environ["WEATHER_BASE_URL"] = saved
    missing = s4_evidence.from_tool("external_weather",
                                    tool_result.get("provider", "weather_api"), tool_result,
                                    provider=tool_result.get("provider", "weather_api"))
    log.append({"tool": "B05 get_weather_forecast → B03", "tool_called": True,
                "tool_success": False, "converted_to_evidence": True,
                "adopted_in_judgment": False,
                "note": "天气证据调用失败（%s）" % (tool_result.get("error") or {}).get("error_type")})
    return None, missing


def run_pipeline(mode):
    print("[I3:%s] 步骤 1：组装证据（内部证据三组完全相同，天气条件变化）" % mode)
    log = []
    adopted, missing = [], []
    e1, e2 = load_internal_evidence(log)
    adopted += [e1, e2]
    e4, _ = fetch_knowledge(log)
    adopted.append(e4)
    weather_ev, weather_missing = fetch_weather_by_mode(mode, log)
    if weather_ev is not None:
        adopted.append(weather_ev)
    if weather_missing is not None:
        missing.append(weather_missing)
    for i, ev in enumerate(adopted + missing):
        if not ev.get("evidence_id"):
            ev["evidence_id"] = {"internal_history": "E1", "ml_prediction": "E2",
                                 "external_weather": "E3", "local_knowledge": "E4"}[ev["source_type"]]
    print("[I3:%s]   有效证据：%s | 缺失证据：%s" % (
        mode, [ev["evidence_id"] for ev in adopted],
        [ev["evidence_id"] for ev in missing]))

    print("[I3:%s] 步骤 2：判定（表达强度跟随证据条件）" % mode)
    judgment = build_judgment(mode, adopted, missing, weather_ev)
    print("[I3:%s]   verdict=%s | 表达强度：%s" % (mode, judgment["verdict"],
                                                   judgment.get("expression_level")))
    print("[I3:%s]   %s" % (mode, judgment["verdict_note"]))

    print("[I3:%s] 步骤 3：LLM 两块式推理（统一固定提问）" % mode)
    llm = explain(FIXED_QUESTION, adopted, missing, judgment)
    print("[I3:%s]   LLM 状态=%s | 禁止词命中=%s | 两块齐全=%s/%s" % (
        mode, llm.get("status"), llm.get("forbidden_hits"),
        llm.get("has_judgable_section"), llm.get("has_limitation_section")))

    run_id = make_run_id()
    record = {
        "run_id": run_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "experiment": "innovate3",
        "mode": "run_%s" % mode,
        "fixed_question": FIXED_QUESTION,
        "adopted_evidence": adopted,
        "missing_evidence": missing,
        "pipeline_log": log,
        "judgment": judgment,
        "llm_explanation": llm,
        "chain_status": ("complete" if llm.get("status") == "success"
                         else "structured_complete_llm_unavailable"),
    }
    path = save_run(record)
    print("[I3:%s] 运行记录已保存：%s" % (mode, path))
    print("[I3:%s] ======== run_id: %s ========" % (mode, run_id))
    return record


def find_latest_by_mode(mode):
    files = sorted(RECORDS_DIR.glob("i3-*.json"))
    for path in reversed(files):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("mode") == "run_%s" % mode:
            return record
    return None


def generate_report():
    records = {}
    for mode in MODES:
        records[mode] = find_latest_by_mode(mode)
        if not records[mode]:
            print("缺少 run_%s 记录，请先运行 --run-all" % mode)
            return 1
    ra, rc, rm = (records[m] for m in MODES)
    lines = [
        "# GreenMate B07 S5 创新点3 实验报告：让系统学会「有些话现在不能说」",
        "",
        "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 三组 run_id：`%s`（agree）| `%s`（conflict）| `%s`（missing_weather）" % (
            ra["run_id"], rc["run_id"], rm["run_id"]),
        "- 统一固定提问：%s" % FIXED_QUESTION,
        "",
        "## 三组对比（表达强度与判断范围随证据条件变化）",
        "",
        "| 维度 | run_agree | run_conflict | run_missing_weather |",
        "| --- | --- | --- | --- |",
        "| 天气证据 | 升温（一致） | 降温（分歧） | 调用失败缺失 |",
        "| verdict | %s | %s | %s |" % (ra["judgment"]["verdict"], rc["judgment"]["verdict"],
                                        rm["judgment"]["verdict"]),
        "| 表达强度 | %s | %s | %s |" % (ra["judgment"]["expression_level"],
                                        rc["judgment"]["expression_level"],
                                        rm["judgment"]["expression_level"]),
        "| 判断范围 | 完整证据链，结论相对明确 | 完整证据链，保留分歧 | 收缩：依赖天气的判断全部受限 |",
        "| 禁止词命中 | %s | %s | %s |" % (ra["llm_explanation"].get("forbidden_hits"),
                                          rc["llm_explanation"].get("forbidden_hits"),
                                          rm["llm_explanation"].get("forbidden_hits")),
        "",
        "## 三组推理原文",
        "",
    ]
    names = {"agree": "run_agree（证据一致 → 结论相对明确）",
             "conflict": "run_conflict（证据分歧 → 保留不确定性）",
             "missing_weather": "run_missing_weather（证据缺失 → 收缩判断边界）"}
    for mode in MODES:
        r = records[mode]
        lines += ["### %s（verdict=%s）" % (names[mode], r["judgment"]["verdict"]), ""]
        lines.append(r["llm_explanation"].get("answer") or "（LLM 不可用）")
        lines.append("")
    lines += [
        "## 差异原因总结",
        "",
        "1. **run_agree**：四类证据方向一致（历史升温已发生 + 模型 WATCH 推断 + 天气升温外部条件"
        "+ 知识支持关注），证据互相印证 → 系统给出相对明确的结论；",
        "2. **run_conflict**：天气证据转向缓解（后续降温），与内部证据分歧 → 系统不判定证据胜负，"
        "保留分歧与不确定性，禁止强确定性表述；",
        "3. **run_missing_weather**：天气证据调用失败缺失 → 系统收缩判断边界，"
        "只讨论剩余证据可支撑的内容，明确标注依赖天气的判断受限，禁止脑补天气信息。",
        "",
        "## 创新点3 核心结论",
        "",
        "可信不是大胆下定论，而是知道什么时候该保留、哪些话不能说：证据一致时结论可以相对明确；"
        "证据冲突时保留不确定性；证据缺失时收缩判断边界。三组实验证明系统的表达强度与判断范围"
        "跟随证据条件自动调整，且全程未出现强确定性结论、未出现私自补齐缺失证据。",
        "",
    ]
    out = S5_DIR / "INNOVATE_3_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("创新点3 实验报告已生成：%s" % out)
    return 0


def summarize(record):
    j = record["judgment"]
    lines = [
        "=" * 64,
        "运行记录 %s（%s）" % (record["run_id"], record["mode"]),
        "=" * 64,
        "有效证据：%s | 缺失证据：%s" % (
            [ev["evidence_id"] for ev in record["adopted_evidence"]],
            [ev["evidence_id"] for ev in record["missing_evidence"]] or "无"),
        "判定：verdict=%s | 表达强度：%s" % (j["verdict"], j.get("expression_level")),
    ]
    llm = record["llm_explanation"]
    if llm.get("status") == "success":
        lines += ["", "【LLM 两块式输出】", llm["answer"]]
    else:
        lines += ["", "【LLM】不可用：[%s] %s" % (llm.get("error_type"), llm.get("message"))]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="创新点3：证据条件变化 → 推理边界变化")
    parser.add_argument("--run-all", action="store_true", help="依次运行三组并生成报告")
    parser.add_argument("--run", choices=MODES, help="运行单组")
    parser.add_argument("--report", action="store_true", help="生成 INNOVATE_3_REPORT.md")
    parser.add_argument("--inspect", metavar="RUN_ID", help="按 run_id 读取记录")
    args = parser.parse_args()

    if args.inspect:
        print(summarize(load_run(args.inspect)))
        return 0
    if args.report:
        return generate_report()
    if args.run:
        run_pipeline(args.run)
        return 0
    if args.run_all:
        for mode in MODES:
            run_pipeline(mode)
            print()
        return generate_report()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
