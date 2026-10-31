"""B08 第二遍正式验证：对 S1~S5 五个固定场景依次验证（只加载冻结快照）。

核心约束：禁止修改系统结构；只加载已经冻结好的 scenario 快照，执行固定提问，
留存完整可复查验证记录。复用 B08 冻结的回放能力 + B01 LLM 能力；不改 B08 基线
代码、不改 B07 机制。

每个场景流程：加载固定场景快照 → 运行固定提问（LLM 输入完全来自快照）→
自动核验（对应各场景验收标准）→ 保存全套验证记录（14 字段）。

用法（项目根目录）：
  python B08/verify.py --all                          # 依次验证 5 个场景 + 生成汇总
  python B08/verify.py --scenario b08_s3_weather      # 验证单场景
  python B08/verify.py --inspect RUN_ID               # 按 run_id 查看当时全套输入/证据/判断
"""

import argparse
import json
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for d in (ROOT / "B08", ROOT / "B07" / "S5", ROOT / "B07" / "S4", ROOT / "B07" / "S3",
          ROOT / "B07" / "S2", ROOT / "B07" / "S1", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from openai import OpenAI  # noqa: E402
from llm import LLMError, get_config, map_error  # noqa: E402

from replay import load_snapshot  # noqa: E402（复用冻结回放能力）

B08_DIR = Path(__file__).resolve().parent
VERIFY_DIR = B08_DIR / "verify"

SCENES = ("b08_s1_steady", "b08_s2_drift", "b08_s3_weather",
          "b08_s4_multi", "b08_s5_degraded")

SYSTEM_PROMPT = (
    "你是 GreenMate 环境分析助手。下面是场景快照中的固定证据与系统判定快照。\n"
    "请基于这些固定输入回答固定提问：\n"
    "1. 基于给出的证据进行判断；证据缺失时明确说明受限，不编造缺失数据；\n"
    "2. 禁止输出『一定、必然、肯定』等强确定性结论；\n"
    "3. 用中文回答，简洁。")

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    return "v8-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


def save_verify(record):
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    path = VERIFY_DIR / ("%s.json" % record["run_id"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_verify(run_id):
    if not re.match(r"^[A-Za-z0-9_-]+$", run_id or ""):
        raise ValueError("非法 run_id：%s" % run_id)
    path = VERIFY_DIR / ("%s.json" % run_id)
    if not path.exists():
        raise FileNotFoundError("未找到验证记录：%s（verify 目录：%s）" % (run_id, VERIFY_DIR))
    return json.loads(path.read_text(encoding="utf-8"))


def load_source_record(snapshot):
    """读取源 run_id 存档（只读，用于回溯模型证据与限制条件）。"""
    src_dir = ROOT / snapshot["source_module"] / "run_records"
    path = src_dir / ("%s.json" % snapshot["source_run_id"])
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def model_evidence_of(snapshot, source_record):
    """模型证据：版本锁定 + 源存档的模型预测快照。"""
    ev = {"model_version": snapshot["model_version"],
          "locked": True,
          "note": "本轮验证固定使用已冻结模型，回放模式不重跑模型"}
    if source_record:
        j = (source_record.get("structured_judgment")
             or source_record.get("step4_structured_judgment") or {})
        pred = (source_record.get("step3_model_prediction")
                or source_record.get("prediction"))
        e2 = next((e for e in source_record.get("adopted_evidence", [])
                   + source_record.get("evidence", [])
                   if e.get("source_type") == "ml_prediction"), None)
        if e2:
            pred = e2.get("result")
        if pred:
            ev["source_prediction"] = {
                "predicted_attention": pred.get("predicted_attention"),
                "probability": pred.get("probability"),
            }
    return ev


def limits_of(snapshot, source_record):
    """限制条件：源存档 judgment_limits + 验证模式限制声明。"""
    limits = []
    if source_record:
        j = (source_record.get("structured_judgment")
             or source_record.get("step4_structured_judgment") or {})
        limits = j.get("judgment_limits") or []
    limits.append("B08 验证模式：输入完全来自冻结快照（回放），未重新查询数据源")
    return limits


def location_of(snapshot):
    weather = snapshot.get("weather_evidence") or {}
    if weather.get("status") not in (None, "unavailable"):
        return "32.06,118.79（南京，天气证据位置）"
    if snapshot.get("scenario_id") == "b08_s5_degraded":
        return "32.06,118.79（南京，天气证据本应覆盖位置，本次缺失）"
    return "无外部天气证据（不适用）"


def run_llm(snapshot):
    """执行固定提问：LLM 输入完全来自快照（固定证据 + 判定快照）。"""
    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type, "message": e.message}

    hist = snapshot["history_series"]
    payload = {
        "scenario": snapshot["scenario_id"],
        "observation": snapshot["observation"],
        "history_summary": {
            "count": len(hist),
            "window": "%s ~ %s" % (hist[0]["timestamp"], hist[-1]["timestamp"]),
            "temperature_first": hist[0]["temperature"],
            "temperature_last": hist[-1]["temperature"],
        },
        "weather_evidence": snapshot["weather_evidence"],
        "knowledge_citation": snapshot["knowledge_citation"],
        "judgment_snapshot": snapshot["judgment_snapshot"],
    }
    user_message = "%s\n\n固定证据与判定快照：\n%s" % (
        snapshot["fixed_question"], json.dumps(payload, ensure_ascii=False, indent=2))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        answer = (resp.choices[0].message.content or "").strip()
        return {"status": "success", "answer": answer, "model": model,
                "elapsed_ms": round((time.time() - started) * 1000)}
    except Exception as e:
        err = map_error(e, base_url, timeout, round((time.time() - started) * 1000))
        err["status"] = "error"
        return err


def live_weather_check():
    """S3 验收附加：真实 API 链路单独校验（实时调用天气 API，只校验链路可用性）。"""
    from B05.tools import get_weather_forecast
    result = get_weather_forecast("32.06,118.79", hours=6)
    return {
        "tool_status": result.get("status"),
        "provider": result.get("provider"),
        "forecast_time_first": ((result.get("data") or {}).get("forecast_time")
                                or [None])[0],
        "note": "真实 API 链路单独校验：验证外部天气链路可用性，不参与场景判定",
    }


def run_checks(scenario_id, snapshot, llm, live_check):
    """按场景验收标准自动核验，返回 (pass, reason, detail)。"""
    verdict = snapshot["judgment_snapshot"]["verdict"]
    answer = llm.get("answer") or ""
    ok_llm = llm.get("status") == "success"
    base = [("快照字段完整", all(snapshot.get(f) not in (None, "", [])
                              for f in ("scenario_id", "observation",
                                        "history_series", "judgment_snapshot"))),
            ("版本标记正确", snapshot["app_version"] == "B08_baseline_01"
             and snapshot["model_version"] == "b06-rf-v1"),
            ("LLM 固定提问执行成功", ok_llm)]

    if scenario_id == "b08_s1_steady":
        extra = [("判定为稳定（stable）", verdict == "stable"),
                 ("未凭空拔高风险（LLM 解释未出现风险升级类结论）",
                  not any(w in answer for w in ("需要重点关注", "风险升高", "WATCH")))]
        reason = ("稳定条件下给出稳定判断，未凭空拔高风险；条件、判断、记录可以对应"
                  if all(p for _, p in base + extra) else "存在未通过项")
    elif scenario_id == "b08_s2_drift":
        extra = [("判定为关注（attention）", verdict == "attention"),
                 ("历史信息参与推理（LLM 解释引用升温/历史数值）",
                  any(w in answer for w in ("升温", "25", "30", "趋势")))]
        reason = ("瞬时读数相近、历史时序不同时趋势与关注程度发生变化，历史信息参与推理"
                  if all(p for _, p in base + extra) else "存在未通过项")
    elif scenario_id == "b08_s3_weather":
        extra = [("判定为 weather_attention（天气影响判断）", verdict == "weather_attention"),
                 ("真实 API 链路校验通过", bool(live_check)
                  and live_check["tool_status"] == "ok"),
                 ("天气证据参与推理（LLM 解释引用天气/降水/云量）",
                  any(w in answer for w in ("天气", "降水", "云量", "阴雨")))]
        reason = ("天气证据参与未来趋势判断，真实 API 链路单独校验通过，"
                  "外部证据影响预测而非仅展示" if all(p for _, p in base + extra)
                  else "存在未通过项")
    elif scenario_id == "b08_s4_multi":
        extra = [("判定为 attention_uncertain（保留差异）", verdict == "attention_uncertain"),
                 ("不强行合并单一确定结论（LLM 解释保留分歧/不确定性）",
                  any(w in answer for w in ("分歧", "不确定", "不一致", "可能缓解")))]
        reason = ("证据冲突时保留差异、输出不确定性，未强行合并成单一确定结论"
                  if all(p for _, p in base + extra) else "存在未通过项")
    else:  # b08_s5_degraded
        weather = snapshot.get("weather_evidence") or {}
        extra = [("天气证据缺失已固化（unavailable）", weather.get("status") == "unavailable"),
                 ("判定为 attention_weather_missing（缩小判断范围）",
                  verdict == "attention_weather_missing"),
                 ("不编造缺失证据（LLM 解释无天气数据陈述且说明受限）",
                  any(w in answer for w in ("受限", "缺失", "不可用", "无法判断"))
                  and not any(w in answer for w in ("降水概率", "云量")))]
        reason = ("某一路证据缺失时系统继续工作、缩小判断范围，未整体崩溃、未编造缺失证据"
                  if all(p for _, p in base + extra) else "存在未通过项")

    details = base + extra
    passed = all(p for _, p in details)
    return passed, reason, [{"check": n, "passed": p} for n, p in details]


def verify_scene(scenario_id):
    """验证单场景：加载快照 → 固定提问 → 核验 → 保存记录。"""
    print("[V8] %s：加载冻结快照" % scenario_id)
    snapshot = load_snapshot(scenario_id)
    source_record = load_source_record(snapshot)

    print("[V8] %s：执行固定提问（LLM 输入完全来自快照）" % scenario_id)
    llm = run_llm(snapshot)

    live_check = None
    if scenario_id == "b08_s3_weather":
        print("[V8] %s：真实 API 链路单独校验" % scenario_id)
        live_check = live_weather_check()
        print("[V8]   live 天气链路：status=%s provider=%s" % (
            live_check["tool_status"], live_check["provider"]))

    passed, reason, details = run_checks(scenario_id, snapshot, llm, live_check)
    print("[V8] %s：核验结果 = %s（%s）" % (scenario_id, "通过 ✅" if passed else "不通过 ❌", reason))

    run_id = make_run_id()
    record = {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "app_version": snapshot["app_version"],
        "model_version": snapshot["model_version"],
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "location": location_of(snapshot),
        "current_state_input": snapshot["observation"],
        "history_window": snapshot["history_series"],
        "weather_evidence": snapshot["weather_evidence"],
        "knowledge_evidence": snapshot["knowledge_citation"],
        "model_evidence": model_evidence_of(snapshot, source_record),
        "tool_runtime_status": {
            "llm": {"status": llm.get("status"), "model": llm.get("model"),
                    "elapsed_ms": llm.get("elapsed_ms")},
            "live_weather_link": live_check,
            "replay_only": True,
        },
        "structured_judgment": snapshot["judgment_snapshot"],
        "llm_explanation": llm,
        "limitations": limits_of(snapshot, source_record),
        "verify_result": {"passed": passed, "reason": reason, "checks": details},
    }
    path = save_verify(record)
    print("[V8] %s：验证记录已保存 %s（run_id=%s）" % (scenario_id, path.name, run_id))
    return record


def build_summary(records):
    lines = [
        "# GreenMate B08 第二遍正式验证汇总（VERIFY_SUMMARY）",
        "",
        "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 验证方式：只加载冻结快照执行固定提问（LLM 输入完全来自快照），"
        "复用 B08 回放能力；不改动基线代码与 B07 机制",
        "- 版本：app_version=%s，model_version=%s（锁定）" % (
            records[0]["app_version"], records[0]["model_version"]),
        "",
        "| scenario_id | run_id | 是否通过 | 简短核验结论 |",
        "| --- | --- | --- | --- |",
    ]
    for r in records:
        vr = r["verify_result"]
        lines.append("| %s | `%s` | **%s** | %s |" % (
            r["scenario_id"], r["run_id"],
            "通过 ✅" if vr["passed"] else "不通过 ❌", vr["reason"]))
    passed_all = all(r["verify_result"]["passed"] for r in records)
    lines += [
        "",
        "## 验收标准对应",
        "",
        "| 场景 | 验收标准 | 核验结果 |",
        "| --- | --- | --- |",
    ]
    for r in records:
        std = {
            "b08_s1_steady": "条件、判断、记录可以对应",
            "b08_s2_drift": "历史信息参与推理",
            "b08_s3_weather": "外部证据影响预测，不只是展示数据（含真实 API 链路单独校验）",
            "b08_s4_multi": "不强行合并成单一确定结论",
            "b08_s5_degraded": "不整体崩溃、不编造缺失证据",
        }[r["scenario_id"]]
        lines.append("| %s | %s | %s |" % (
            r["scenario_id"], std,
            "✅ 达成" if r["verify_result"]["passed"] else "❌ 未达成"))
    lines += [
        "",
        "## 总结论",
        "",
        ("✅ 五个场景全部通过验证：S1~S5 各有独立 run_id，记录齐全，"
         "可回溯当时全部输入、版本、判断结果。" if passed_all else
         "❌ 存在未通过场景，请按各场景核验详情排查。"),
        "",
        "查询入口：python B08/verify.py --inspect <run_id>（查看当时全套输入/证据/判断）。",
        "",
    ]
    return "\n".join(lines)


def inspect(run_id):
    record = load_verify(run_id)
    lines = [
        "=" * 64,
        "B08 验证记录 %s" % run_id,
        "=" * 64,
        "scenario_id: %s | app_version: %s | model_version: %s | analysis_time: %s" % (
            record["scenario_id"], record["app_version"], record["model_version"],
            record["analysis_time"]),
        "location: %s" % record["location"],
        "当前状态输入: %s" % json.dumps(record["current_state_input"], ensure_ascii=False),
        "历史时间窗口: %d 点（%s ~ %s）" % (
            len(record["history_window"]), record["history_window"][0]["timestamp"],
            record["history_window"][-1]["timestamp"]),
        "天气证据: %s" % json.dumps(record["weather_evidence"], ensure_ascii=False)[:200],
        "知识证据: %s" % json.dumps(record["knowledge_evidence"], ensure_ascii=False)[:200],
        "模型证据: %s" % json.dumps(record["model_evidence"], ensure_ascii=False),
        "工具/运行状态: %s" % json.dumps(record["tool_runtime_status"], ensure_ascii=False)[:200],
        "结构化判断: %s" % json.dumps(record["structured_judgment"], ensure_ascii=False),
        "限制条件: %s" % json.dumps(record["limitations"], ensure_ascii=False)[:300],
        "核验结果: 通过=%s（%s）" % (record["verify_result"]["passed"],
                                     record["verify_result"]["reason"]),
        "",
        "【LLM 解释结果】",
        record["llm_explanation"].get("answer") or
        ("LLM 不可用：[%s] %s" % (record["llm_explanation"].get("error_type"),
                                  record["llm_explanation"].get("message"))),
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="B08 第二遍正式验证")
    parser.add_argument("--all", action="store_true", help="依次验证 5 个场景并生成汇总")
    parser.add_argument("--scenario", choices=SCENES, help="验证单场景")
    parser.add_argument("--inspect", metavar="RUN_ID", help="按 run_id 查看全套记录")
    args = parser.parse_args()

    if args.inspect:
        print(inspect(args.inspect))
        return 0
    if args.all:
        records = [verify_scene(s) for s in SCENES]
        summary = build_summary(records)
        (VERIFY_DIR / "VERIFY_SUMMARY.md").write_text(summary, encoding="utf-8")
        print("\n[汇总已生成] %s" % (VERIFY_DIR / "VERIFY_SUMMARY.md"))
        print(summary)
        return 0 if all(r["verify_result"]["passed"] for r in records) else 1
    if args.scenario:
        verify_scene(args.scenario)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
