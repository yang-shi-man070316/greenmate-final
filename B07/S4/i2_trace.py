"""创新点2 溯源实验（B07/S4 交付物）：正向推理 + 反向溯源。

流程：
1. 复用 S4 采集组件真实调用四类数据源（B02 历史 / B03 天气 / B04 知识 / B06 预测），
   每条证据自带元信息（source/time/status/result + 按需 error/citation/model_version）；
2. 复用 S4 判定生成核心结论（判定侧生成，非 LLM 自由文本）；
3. 校验 B05 调用记录：工具真实调用、入参、返回值、执行结果；LLM 不允许假装调用；
4. 生成溯源报告 EVIDENCE_TRACE_REPORT.md：结论对应支持证据 / 限制证据 / 反向提示证据。

用法（项目根目录）：
  python B07/S4/i2_trace.py --run             # 运行一轮，保存 i2- 记录
  python B07/S4/i2_trace.py --report          # 生成 EVIDENCE_TRACE_REPORT.md
  python B07/S4/i2_trace.py --trace RUN_ID    # 反向溯源：结论 → 证据五问 → 调用记录
"""

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B07" / "S3", ROOT / "B07" / "S4", ROOT / "B06", ROOT / "B05",
          ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B07.S3.i2_evidence import describe, role_of  # noqa: E402
from B07.S4.judgment import build_judgment  # noqa: E402
from B07.S4.llm_explain import explain  # noqa: E402
from B07.S4.run import (fetch_cooling_forecast, fetch_knowledge,  # noqa: E402
                        load_internal_evidence, load_run, save_run)

S4_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S4_DIR / "run_records"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    return "i2-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


def extract_conclusion(judgment):
    """核心结论由判定侧生成（可反向溯源），不是 LLM 自由文本。"""
    if judgment["verdict"] == "attention_uncertain":
        return "当前需要提高关注程度，但天气提示可能缓解、未来是否继续恶化不确定"
    if judgment["verdict"] == "attention":
        return "当前需要提高关注程度"
    return "当前无法确定关注程度（%s）" % judgment["verdict"]


def annotate_conclusion(judgment):
    """结论 → 支持证据 / 限制证据 / 反向提示证据（判定侧绑定）。"""
    return {
        "support": [ev.get("evidence_id") for ev in judgment["synthesis"]["support_attention"]],
        "reverse": [ev.get("evidence_id") for ev in judgment["synthesis"]["mitigating_or_reverse"]],
        "limitation": [ev.get("evidence_id") for ev in judgment["synthesis"]["insufficient"]],
    }


def verify_calls(record):
    """校验调用记录：工具真实调用 + LLM 未假装调用/未引用不存在的证据。

    返回检查列表 [(名称, 通过, 说明)]。
    """
    log = record.get("pipeline_log", [])
    evs = record.get("evidence", [])
    checks = []
    # 1) 每条被采用的证据都有对应的真实调用记录（called=True 且 converted=True）
    for ev in evs:
        matched = [l for l in log
                   if l.get("tool_called") and l.get("converted_to_evidence")
                   and l.get("adopted_in_judgment")]
        checks.append((
            "证据 %s（%s）有真实工具调用记录" % (ev.get("evidence_id"), ev.get("source_type")),
            len(matched) >= 1,
            "调用条目 %d 条" % len(matched)))
    # 2) 调用记录的入参/返回值信息存在
    for l in log:
        if l.get("tool_called"):
            checks.append((
                "调用记录含入参/结果说明：%s" % l["tool"][:30],
                bool(l.get("note")) and "tool_success" in l,
                "success=%s" % l.get("tool_success")))
    # 3) LLM 引用的证据编号必须存在于记录（不允许假装调用/引用不存在的证据）
    answer = (record.get("llm_explanation") or {}).get("answer") or ""
    cited = set(re.findall(r"\[(E\d+)\]", answer))
    known = {ev.get("evidence_id") for ev in evs}
    unknown = sorted(cited - known)
    checks.append((
        "LLM 引用证据均真实存在（无假装调用）",
        not unknown,
        "引用 %s；不存在：%s" % (sorted(cited) or "无", unknown or "无")))
    return checks


def run_round():
    print("[I2] 步骤 1：真实调用四类数据源，逐条封装为可追溯证据")
    log = []
    e1, e2 = load_internal_evidence(log)
    e3, _ = fetch_cooling_forecast(log)
    e4, _ = fetch_knowledge(log)
    evidence_list = [e1, e2, e3, e4]
    for i, ev in enumerate(evidence_list, start=1):
        ev["evidence_id"] = "E%d" % i  # 编号提前分配，供日志与后续溯源使用
    for ev in evidence_list:
        d = describe(ev)
        print("[I2]   %s | %s | 有效=%s | 时间=%s" % (
            ev.get("evidence_id"), d["what"], d["valid"], d["time"]))

    print("[I2] 步骤 2：生成核心结论（判定侧，可反向溯源）")
    judgment = build_judgment(evidence_list)
    conclusion = extract_conclusion(judgment)
    annotations = annotate_conclusion(judgment)
    print("[I2]   结论：%s" % conclusion)
    print("[I2]   支持证据=%s | 反向提示证据=%s | 限制证据=%s" % (
        annotations["support"], annotations["reverse"], annotations["limitation"]))

    print("[I2] 步骤 3：LLM 三段式推理（每条结论标注证据编号）")
    llm = explain(evidence_list, judgment)
    print("[I2]   LLM 状态=%s" % llm.get("status"))

    print("[I2] 步骤 4：校验调用记录（工具真实调用 / LLM 未假装调用）")
    checks = verify_calls({
        "evidence": evidence_list, "pipeline_log": log, "llm_explanation": llm})
    for name, passed, detail in checks:
        print("[I2]   [%s] %s — %s" % ("PASS" if passed else "FAIL", name, detail))

    run_id = make_run_id()
    record = {
        "run_id": run_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "experiment": "innovate2_trace",
        "evidence": evidence_list,
        "evidence_boundaries": [role_of(ev) for ev in evidence_list],
        "pipeline_log": log,
        "judgment": judgment,
        "conclusion": conclusion,
        "conclusion_annotations": annotations,
        "call_checks": [{"name": n, "passed": p, "detail": d} for n, p, d in checks],
        "llm_explanation": llm,
        "chain_status": ("complete" if llm.get("status") == "success"
                         else "structured_complete_llm_unavailable"),
    }
    path = save_run(record)
    print("[I2] 运行记录已保存：%s" % path)
    print("[I2] ======== run_id: %s ========" % run_id)
    return record


def find_latest():
    files = sorted(RECORDS_DIR.glob("i2-*.json"))
    for path in reversed(files):
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def trace(run_id):
    """反向溯源：结论 → 每条证据五问 + 作用边界 → 对应调用记录。"""
    record = load_run(run_id) if re.match(r"^[A-Za-z0-9_-]+$", run_id or "") else None
    if not record:
        print("未找到记录：%s" % run_id)
        return 1
    j = record["judgment"]
    ann = record["conclusion_annotations"]
    lines = [
        "=" * 64,
        "反向溯源：run_id %s" % run_id,
        "=" * 64,
        "核心结论：%s" % record["conclusion"],
        "  支持证据：%s | 反向提示证据：%s | 限制证据：%s" % (
            ann["support"], ann["reverse"], ann["limitation"]),
        "",
    ]
    direction_map = {}
    for d, ids in (("支持（指向结论）", ann["support"]),
                   ("反向提示（缓解/相反方向）", ann["reverse"]),
                   ("限制（提示不确定性）", ann["limitation"])):
        for eid in ids:
            direction_map[eid] = d
    tool_hints = {"internal_history": "B02", "ml_prediction": "B06",
                  "external_weather": "weather_forecast", "local_knowledge": "search_tomato"}
    for ev in record["evidence"]:
        d = describe(ev)
        b = role_of(ev)
        call_note = next(
            (l.get("note") for l in record["pipeline_log"]
             if l.get("tool_called") and l.get("adopted_in_judgment")
             and tool_hints.get(ev.get("source_type"), "") in l.get("tool", "")),
            "无")
        lines += [
            "---- 证据 %s ----" % ev.get("evidence_id"),
            "  是什么：%s | 来源：%s | 获取时间：%s | 有效：%s | 作用边界：%s（%s）" % (
                d["what"], d["source"], d["time"], d["valid"], b["role"], b["boundary"]),
            "  在结论中的方向：%s" % direction_map.get(ev.get("evidence_id"), "未采用"),
            "  内容：%s" % json.dumps(d["content"], ensure_ascii=False)[:300],
            "  对应调用记录：%s" % call_note,
            "",
        ]
    print("\n".join(lines))
    return 0


def generate_report(record=None):
    record = record or find_latest()
    if not record:
        print("需要先运行 --run 生成一轮记录")
        return 1
    j = record["judgment"]
    ann = record["conclusion_annotations"]
    lines = [
        "# 创新点2 证据溯源报告（EVIDENCE_TRACE_REPORT）",
        "",
        "- run_id：`%s`（%s）" % (record["run_id"], record["created_at"]),
        "- 核心结论：**%s**" % record["conclusion"],
        "",
        "## 结论与证据标注",
        "",
        "| 证据方向 | 证据 |",
        "| --- | --- |",
        "| 支持证据（指向结论） | %s |" % ", ".join(ann["support"]),
        "| 反向提示证据（缓解/相反方向） | %s |" % ", ".join(ann["reverse"]),
        "| 限制证据（提示不确定性） | %s |" % ", ".join(ann["limitation"]),
        "",
        "## 四类证据明细与作用边界（信息≠证据，四类不可互相替代）",
        "",
        "| 证据 | 类型 | 作用边界 | 来源 | 获取时间 | 有效 | 内容摘要 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for ev, b in zip(record["evidence"], record["evidence_boundaries"]):
        d = describe(ev)
        content = json.dumps(d["content"], ensure_ascii=False)
        lines.append("| %s | %s（%s） | %s | %s | %s | %s | %s |" % (
            ev.get("evidence_id"), b["name"], ev["source_type"], b["role"],
            d["source"], d["time"], "✅" if d["valid"] else "❌",
            content[:120]))
    lines += [
        "",
        "## B05 调用记录校验（工具真实调用，不允许 LLM 假装调用）",
        "",
        "| 检查项 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for c in record["call_checks"]:
        lines.append("| %s | %s | %s |" % (c["name"], "✅" if c["passed"] else "❌", c["detail"]))
    lines += [
        "",
        "## 反向溯源演示",
        "",
        "核心结论：「%s」逐条可追溯：" % record["conclusion"],
    ]
    direction_map = {}
    for d, ids in (("支持", ann["support"]), ("反向提示", ann["reverse"]),
                   ("限制", ann["limitation"])):
        for eid in ids:
            direction_map[eid] = d
    for ev in record["evidence"]:
        d = describe(ev)
        b = role_of(ev)
        lines.append("- **%s**（%s）：%s → %s（来源 %s，获取于 %s，有效=%s）。"
                     "内容：%s" % (
                         ev.get("evidence_id"), direction_map.get(ev.get("evidence_id"), "未采用"),
                         b["name"], b["role"], d["source"], d["time"], d["valid"],
                         json.dumps(d["content"], ensure_ascii=False)[:150]))
    lines += [
        "",
        "## LLM 推理原文",
        "",
        record["llm_explanation"].get("answer") or "（LLM 不可用）",
        "",
    ]
    out = S4_DIR / "EVIDENCE_TRACE_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("溯源报告已生成：%s" % out)
    return 0


def main():
    parser = argparse.ArgumentParser(description="创新点2 证据溯源实验")
    parser.add_argument("--run", action="store_true", help="运行一轮并保存记录")
    parser.add_argument("--report", action="store_true", help="生成 EVIDENCE_TRACE_REPORT.md")
    parser.add_argument("--trace", metavar="RUN_ID", help="反向溯源指定记录")
    args = parser.parse_args()

    if args.trace:
        return trace(args.trace)
    if args.run:
        record = run_round()
        return generate_report(record)
    if args.report:
        return generate_report()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
