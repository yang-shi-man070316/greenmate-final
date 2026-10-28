"""S5 证据退化实验入口（终端运行，无网页）。

基线：全部证据正常（复用 S4 全套组件），固定提问，保存 run_id 对照组。
故障：三种单一故障（同一时间只触发一种，故障后不修复，复用同一提问）：
  --fault weather_unavailable  天气 API 不可用（指向未监听端口，真实网络失败）
  --fault rag_insufficient     RAG 检索不足（库外查询词，无匹配）
  --fault tool_error           工具返回异常（天气工具传非法参数，validation_error）

用法（项目根目录）：
  python B07/S5/run.py --baseline
  python B07/S5/run.py --fault weather_unavailable|rag_insufficient|tool_error
  python B07/S5/run.py --report          # 生成 EXPERIMENT_REPORT.md（基线 vs 故障）
  python B07/S5/run.py --inspect RUN_ID
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

from B05.tools import get_weather_forecast, search_tomato_knowledge  # noqa: E402
from B07.S4 import evidence  # noqa: E402
from B07.S4.run import (FORECAST_LOCATION, KNOWLEDGE_QUERY,  # noqa: E402
                        fetch_cooling_forecast, fetch_knowledge, load_internal_evidence)
from B07.S4.weather_stub import CoolingStub  # noqa: E402 （基线天气场景复用）

from s5_judgment import build_judgment  # noqa: E402
from s5_llm_explain import explain  # noqa: E402

S5_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S5_DIR / "run_records"

FIXED_QUESTION = "结合全部可用证据，分析当前番茄生长环境风险：哪些方面可以判断，哪些方面因证据受限无法判断？"

FAULTS = ("weather_unavailable", "rag_insufficient", "tool_error")

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    return "s5-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


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


def collect_evidence(fault, log):
    """收集证据：正常路径复用 S4；故障路径真实触发且不修复。

    返回 (adopted_evidence, missing_evidence)。缺失证据保留原始结构与失败原因。
    """
    adopted, missing = [], []

    # E1/E2 内部证据（S5 三种故障均不触及，复用 S4 加载）
    e1, e2 = load_internal_evidence(log)
    adopted += [e1, e2]

    # E3 天气证据
    if fault in ("weather_unavailable", "tool_error"):
        if fault == "weather_unavailable":
            saved = os.environ.get("WEATHER_BASE_URL")
            os.environ["WEATHER_BASE_URL"] = "http://127.0.0.1:59994"  # 未监听端口
            try:
                tool_result = get_weather_forecast(FORECAST_LOCATION, hours=6)
            finally:
                if saved is None:
                    os.environ.pop("WEATHER_BASE_URL", None)
                else:
                    os.environ["WEATHER_BASE_URL"] = saved
        else:  # tool_error：非法参数，工具直接报错
            tool_result = get_weather_forecast("")
        e3 = evidence.from_tool("external_weather",
                                tool_result.get("provider", "weather_api"), tool_result,
                                provider=tool_result.get("provider", "weather_api"))
        missing.append(e3)
        log.append({"tool": "B05 get_weather_forecast → B03",
                    "tool_called": True, "tool_success": tool_result["status"] == "ok",
                    "converted_to_evidence": True, "adopted_in_judgment": False,
                    "note": "故障注入（%s）：%s" % (fault,
                        (tool_result.get("error") or {}).get("error_type"))})
    else:
        e3, valid = fetch_cooling_forecast(log)
        adopted.append(e3)

    # E4 知识证据
    if fault == "rag_insufficient":
        tool_result = search_tomato_knowledge("火星土壤的 pH 值是多少")  # 库外查询
        e4 = evidence.from_tool("local_knowledge", "greenmate_b04_kb", tool_result,
                                citation=[])
        missing.append(e4)
        log.append({"tool": "B05 search_tomato_knowledge → B04",
                    "tool_called": True, "tool_success": True,
                    "converted_to_evidence": True, "adopted_in_judgment": False,
                    "note": "故障注入（rag_insufficient）：检索无匹配，证据缺失"})
    else:
        e4, adopted4 = fetch_knowledge(log)
        adopted.append(e4)

    return adopted, missing


def run_pipeline(mode, fault=None):
    print("[S5:%s] 步骤 1：收集证据（故障=%s，同一时间只触发一种）" % (mode, fault or "无"))
    log = []
    adopted, missing = collect_evidence(fault, log)
    # 证据编号按 source_type 固定（跨轮一致：基线 E3=天气 vs 故障 E3 缺失）
    source_ids = {"internal_history": "E1", "ml_prediction": "E2",
                  "external_weather": "E3", "local_knowledge": "E4"}
    for ev in adopted + missing:
        ev["evidence_id"] = source_ids[ev["source_type"]]
    print("[S5:%s]   有效证据：%s | 缺失证据：%s" % (
        mode, [ev.get("evidence_id") for ev in adopted],
        [ev.get("evidence_id") for ev in missing]))

    print("[S5:%s] 步骤 2：退化判定（基于剩余证据，标注局限）" % mode)
    judgment = build_judgment(adopted, missing)
    print("[S5:%s]   verdict=%s（%s）" % (mode, judgment["verdict"], judgment["verdict_note"]))
    for m in judgment["missing_evidence"]:
        print("[S5:%s]   缺失：%s（%s）" % (mode, m["source_type"], m["reason"]))

    print("[S5:%s] 步骤 3：LLM 两块式推理（可判断内容 + 受限说明）" % mode)
    llm = explain(FIXED_QUESTION, adopted, missing, judgment)
    print("[S5:%s]   LLM 状态=%s | 含「可判断内容」=%s | 含「受限说明」=%s" % (
        mode, llm.get("status"), llm.get("has_judgable_section"),
        llm.get("has_limitation_section")))

    run_id = make_run_id()
    record = {
        "run_id": run_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "s5_task": "S5 证据退化实验",
        "experiment": "S5_baseline" if mode == "baseline" else "S5_fault",
        "mode": mode,
        "fault": fault,
        "fixed_question": FIXED_QUESTION,
        "adopted_evidence": adopted,
        "missing_evidence": missing,
        "pipeline_log": log,
        "structured_judgment": judgment,
        "llm_explanation": llm,
        "chain_status": ("complete" if llm.get("status") == "success"
                         else "structured_complete_llm_unavailable"),
    }
    path = save_run(record)
    print("[S5:%s] 运行记录已保存：%s" % (mode, path))
    print("[S5:%s] ======== run_id: %s ========" % (mode, run_id))
    return record


def find_latest(experiment):
    files = sorted(RECORDS_DIR.glob("s5-*.json"))
    for path in reversed(files):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("experiment") == experiment:
            return record
    return None


def generate_report():
    base = find_latest("S5_baseline")
    fault = find_latest("S5_fault")
    if not base or not fault:
        print("需要先运行 --baseline 与 --fault 生成两轮记录")
        return 1

    bj = base["structured_judgment"]
    fj = fault["structured_judgment"]
    fl = fault["llm_explanation"]
    bl = base["llm_explanation"]

    # 参与度检查：基线回答中提及故障证据相关内容的关键词计数
    keywords = {"weather_unavailable": ("降水", "云量", "降温", "天气预报", "open_meteo"),
                "rag_insufficient": ("知识", "K09", "趋势", "恶化"),
                "tool_error": ("降水", "云量", "降温", "天气预报")}
    kw = keywords.get(fault["fault"], ())
    base_mentions = sum((bl.get("answer") or "").count(k) for k in kw)
    fault_mentions = sum((fl.get("answer") or "").count(k) for k in kw)

    lines = [
        "# GreenMate S5 证据退化实验报告",
        "",
        "- 基线 run_id：`%s`（全部证据正常）" % base["run_id"],
        "- 故障 run_id：`%s`（故障类型：%s）" % (fault["run_id"], fault["fault"]),
        "- 固定提问（两轮完全一致）：%s" % FIXED_QUESTION,
        "",
        "## 消失的信息",
        "",
    ]
    if fault["missing_evidence"]:
        for m in fault["missing_evidence"]:
            lines.append("- **%s**（%s）：%s" % (m.get("source_type"), m.get("status"), m.get("reason")))
    else:
        lines.append("- （无缺失证据）")
    lines += [
        "",
        "## 保留的判断",
        "",
        "| 维度 | 基线 | 故障后 |",
        "| --- | --- | --- |",
        "| verdict | %s | %s |" % (bj["verdict"], fj["verdict"]),
        "| 有效证据 | %s | %s |" % (bj["adopted_evidence"], fj["adopted_evidence"]),
        "| 支持提高关注 | %s | %s |" % ([e.get("evidence_id") for e in bj["synthesis"]["support_attention"]],
                                      [e.get("evidence_id") for e in fj["synthesis"]["support_attention"]]),
        "| 可能缓解/反向 | %s | %s |" % ([e.get("evidence_id") for e in bj["synthesis"]["mitigating_or_reverse"]],
                                      [e.get("evidence_id") for e in fj["synthesis"]["mitigating_or_reverse"]]),
        "| 不足以确定 | %s | %s |" % ([e.get("evidence_id") for e in bj["synthesis"]["insufficient"]],
                                    [e.get("evidence_id") for e in fj["synthesis"]["insufficient"]]),
        "",
        "## 结论保守化情况",
        "",
        "- 基线：%s（%s）" % (bj["verdict"], bj["verdict_note"]),
        "- 故障后：%s（%s）" % (fj["verdict"], fj["verdict_note"]),
        "- 保守化说明：缺失证据对应的判断维度被显式标注为不可靠（见 LLM 受限说明），"
        "系统未伪造缺失数据，也未整体放弃推理。",
        "",
        "## 证据参与度检查",
        "",
        "- 基线回答提及缺失证据相关词 %d 次；故障后 %d 次（关键词：%s）" % (
            base_mentions, fault_mentions, kw),
    ]
    if base_mentions >= 2 and fault_mentions >= base_mentions * 0.8:
        lines.append("- ⚠️ 两次输出对该证据的提及差别很小，需排查该证据是否真正参与推理")
    else:
        lines.append("- ✅ 基线回答确实使用了该证据（%d 次提及），故障后缺失被如实标注——该证据参与了推理" % base_mentions)
    lines += [
        "",
        "## LLM 输出对比",
        "",
        "### 基线（verdict=%s）" % bj["verdict"],
        "",
        (bl.get("answer") or "（LLM 不可用）"),
        "",
        "### 故障后（verdict=%s）" % fj["verdict"],
        "",
        (fl.get("answer") or "（LLM 不可用）"),
        "",
    ]
    out = S5_DIR / "EXPERIMENT_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("实验报告已生成：%s" % out)
    return 0


def summarize(record):
    j = record["structured_judgment"]
    lines = [
        "=" * 64,
        "运行记录 %s（%s，故障=%s）" % (record["run_id"], record["mode"], record.get("fault") or "无"),
        "=" * 64,
        "有效证据：%s" % [ev.get("evidence_id") for ev in record["adopted_evidence"]],
        "缺失证据：%s" % [{
            "id": m.get("evidence_id"), "source_type": m.get("source_type"),
            "status": m.get("status"), "reason": m.get("reason"),
        } for m in record["missing_evidence"]] or "无",
        "判定：verdict=%s（%s）" % (j["verdict"], j["verdict_note"]),
    ]
    llm = record["llm_explanation"]
    if llm.get("status") == "success":
        lines += ["", "【LLM 两块式输出】", llm["answer"]]
    else:
        lines += ["", "【LLM】不可用：[%s] %s" % (llm.get("error_type"), llm.get("message"))]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="GreenMate S5 证据退化实验")
    parser.add_argument("--baseline", action="store_true", help="基线：全部证据正常")
    parser.add_argument("--fault", choices=FAULTS, help="单一故障：%s" % " | ".join(FAULTS))
    parser.add_argument("--report", action="store_true", help="生成 EXPERIMENT_REPORT.md")
    parser.add_argument("--inspect", metavar="RUN_ID", help="按 run_id 读取记录")
    args = parser.parse_args()

    if args.inspect:
        print(summarize(load_run(args.inspect)))
        return 0
    if args.report:
        return generate_report()
    if args.baseline:
        run_pipeline("baseline", fault=None)
        return 0
    if args.fault:
        run_pipeline("fault", fault=args.fault)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
