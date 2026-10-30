"""VIEW3 证据空间视图渲染器（只读）。

全局规则：只读取存档数据——禁止重跑实验、禁止调用 LLM、禁止重算模型、
禁止请求接口，全程只读。本模块只 import json/pathlib/re。

数据来源（全部只读 json 读取）：
1. i3 固定 run_id 主存档：五类证据（历史/天气/知识/模型 + 工具与运行状态）；
2. S4 存档（最新 S4_with_evidence）：证据分歧案例（方向分类引用存档自带 synthesis，
   不新增推理）；
3. S5 存档（最新 S5_fault weather_unavailable）：证据缺失案例（缺失原因引用存档自带
   missing_evidence，影响引用存档自带 verdict_note）。

用法（项目根目录）：
  python B07/VIEW/v3_evidence/evidence_render.py --run-id i3-20261031013638-f78ead
  python B07/VIEW/v3_evidence/evidence_render.py --run-id xxx --out VIEW3_REPORT.md
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
I3_DIR = ROOT / "B07" / "S5" / "run_records"
S4_DIR = ROOT / "B07" / "S4" / "run_records"
S5_DIR = ROOT / "B07" / "S5" / "run_records"

DEFAULT_RUN_ID = "i3-20261031013638-f78ead"

TYPE_NAMES = {
    "internal_history": "历史证据",
    "external_weather": "天气证据",
    "local_knowledge": "知识证据",
    "ml_prediction": "模型证据",
}

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_json(run_id, records_dir):
    if not re.match(r"^[A-Za-z0-9_-]+$", run_id or ""):
        raise ValueError("非法 run_id：%s" % run_id)
    path = records_dir / ("%s.json" % run_id)
    if not path.exists():
        raise FileNotFoundError("存档不存在：%s（目录：%s）" % (run_id, records_dir))
    return json.loads(path.read_text(encoding="utf-8"))


def find_latest(records_dir, experiment, fault=None):
    files = sorted(records_dir.glob("*.json"))
    for path in reversed(files):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if record.get("experiment") == experiment and (fault is None or record.get("fault") == fault):
            return record
    return None


def _summary(ev, max_len=160):
    """证据内容摘要（只读提取，不堆砌全文）。"""
    st = ev.get("source_type")
    result = ev.get("result") or {}
    if st == "internal_history":
        return "窗口 %s，温度 %s→%s℃，%s" % (
            result.get("window", "?"), result.get("temperature_first", "?"),
            result.get("temperature_last", "?"), result.get("trend", "?"))
    if st == "ml_prediction":
        return "predicted_attention=%s，概率=%s（%s）" % (
            result.get("predicted_attention", "?"), result.get("probability", {}),
            ev.get("model_version", "?"))
    if st == "external_weather":
        hourly = (result.get("forecast") or {}).get("hourly") or []
        temps = [h.get("temperature_2m") for h in hourly if h.get("temperature_2m") is not None]
        return "未来 %d 小时预报，温度 %s℃（provider=%s，forecast_time 首点=%s）" % (
            len(hourly), ", ".join(str(t) for t in temps[:3]) or "未存储",
            ev.get("provider", "?"), (ev.get("forecast_time") or ["?"])[0])
    if st == "local_knowledge":
        segments = result.get("segments") or []
        ids = [s.get("id") for s in segments] or (["无匹配"] if result.get("no_match") else ["?"])
        citation = ev.get("citation") or []
        return "检索「%s」命中 %s，citation=%d 条（%s）" % (
            result.get("query", "?"), ids, len(citation),
            "; ".join("%s→%s" % (c.get("id"), c.get("source")) for c in citation[:2]) or "无")
    return json.dumps(result, ensure_ascii=False)[:max_len]


def _validity(ev):
    """有效性三态（只读映射，不新增推理）。"""
    status = ev.get("status")
    if status == "ok" and not (ev.get("result") or {}).get("no_match"):
        return "有效（ok）"
    if status == "ok":
        return "有效但检索无匹配（ok / no_match）"
    if status == "unavailable":
        return "不可用（unavailable）"
    return "无效（error）"


def extract_main(record):
    """主存档：五类证据（三问）+ 工具与运行状态。"""
    evidence = {TYPE_NAMES[ev["source_type"]]: {
        "source": ev.get("source"), "content": _summary(ev),
        "validity": _validity(ev), "status": ev.get("status"),
    } for ev in record.get("adopted_evidence", [])
        if ev.get("source_type") in TYPE_NAMES}
    tools = record.get("pipeline_log", [])
    return {
        "run_id": record.get("run_id"),
        "created_at": record.get("created_at"),
        "mode": record.get("mode"),
        "verdict": (record.get("judgment") or {}).get("verdict", "未存储"),
        "verdict_note": (record.get("judgment") or {}).get("verdict_note", "未存储"),
        "evidence": evidence,
        "tools": tools,
        "chain_status": record.get("chain_status", "?"),
    }


def extract_s4_case():
    """S4 分歧案例：方向分类引用存档自带 synthesis（零新推理）。

    跳过测试 mock 记录（judgment.verdict 为空的记录），只采用真实运行记录。
    """
    def judgment_of(r):
        return (r.get("structured_judgment") or r.get("judgment") or {})

    record = find_latest(S4_DIR, "S4_with_evidence")
    if not record or not judgment_of(record).get("verdict") \
            or not judgment_of(record).get("synthesis"):
        # 兜底：逐个向前找第一条判定字段齐全的真实记录（跳过测试 mock）
        files = sorted(S4_DIR.glob("s4-*.json"))
        record = None
        for path in reversed(files):
            try:
                r = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if (r.get("experiment") == "S4_with_evidence"
                    and judgment_of(r).get("verdict")
                    and judgment_of(r).get("synthesis")):
                record = r
                break
    if not record:
        return None
    judgment = record.get("structured_judgment") or record.get("judgment") or {}
    synthesis = judgment.get("synthesis") or {}
    def ids(part):
        return [ev.get("evidence_id") for ev in synthesis.get(part, [])]
    return {
        "run_id": record.get("run_id"),
        "verdict": judgment.get("verdict"),
        "support": ids("support_attention"),
        "reverse": ids("mitigating_or_reverse"),
        "limitation": ids("insufficient"),
        "verdict_note": judgment.get("verdict_note"),
    }


def extract_s5_case():
    """S5 缺失案例：缺失原因引用存档自带 missing_evidence（零新推理）。

    跳过测试 mock 记录（无 missing_evidence 或 judgment 为空的记录）。
    """
    def judgment_of(r):
        return (r.get("structured_judgment") or r.get("judgment") or {})

    record = find_latest(S5_DIR, "S5_fault", fault="weather_unavailable")
    if not record or not record.get("missing_evidence") \
            or not judgment_of(record).get("verdict"):
        files = sorted(S5_DIR.glob("s5-*.json"))
        record = None
        for path in reversed(files):
            try:
                r = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if (r.get("experiment") == "S5_fault" and r.get("fault") == "weather_unavailable"
                    and r.get("missing_evidence")
                    and judgment_of(r).get("verdict")):
                record = r
                break
    if not record:
        return None
    missing = record.get("missing_evidence") or []
    adopted = [ev.get("evidence_id") for ev in record.get("adopted_evidence", [])]
    judgment = record.get("structured_judgment") or record.get("judgment") or {}
    return {
        "run_id": record.get("run_id"),
        "fault": record.get("fault"),
        "adopted": adopted,
        "missing": [{
            "evidence_id": m.get("evidence_id"),
            "source_type": m.get("source_type"),
            "status": m.get("status"),
            "reason": (m.get("error") or {}).get("message", "未知原因"),
        } for m in missing],
        "verdict": judgment.get("verdict"),
        "verdict_note": judgment.get("verdict_note"),
    }


def render_md(main, s4_case, s5_case):
    lines = [
        "=" * 64,
        "GreenMate VIEW3 · 证据空间视图",
        "=" * 64,
        "run_id: %s | 创建于 %s | mode: %s" % (main["run_id"], main["created_at"], main["mode"]),
        "",
        "本视图为只读渲染：未重跑实验、未调用 LLM、未重算模型、未请求接口。"
        "分歧方向引用 S4 存档自带 synthesis 分类；缺失原因引用 S5 存档自带 missing_evidence。",
        "",
        "## 证据空间总览（本 run_id 的判断依据）",
        "判定：%s（%s）" % (main["verdict"], main["verdict_note"]),
        "",
    ]
    for name in ("历史证据", "天气证据", "知识证据", "模型证据"):
        ev = main["evidence"].get(name)
        if not ev:
            lines.append("### %s" % name)
            lines.append("（本存档未包含该类证据，如实标注）")
            lines.append("")
            continue
        lines += [
            "### %s" % name,
            "来源：%s" % ev["source"],
            "内容：%s" % ev["content"],
            "有效性：%s" % ev["validity"],
            "",
        ]
    lines += [
        "### 工具与运行状态",
        "链状态：%s" % main["chain_status"],
    ]
    for t in main["tools"]:
        lines.append("- %s | 调用=%s | 成功=%s | 转为证据=%s | 采用=%s | %s" % (
            t.get("tool", "?"), t.get("tool_called"), t.get("tool_success"),
            t.get("converted_to_evidence"), t.get("adopted_in_judgment"), t.get("note", "")))
    lines += [
        "",
        "## 证据分歧案例（S4 存档，方向分类引用存档 synthesis）",
    ]
    if s4_case:
        lines += [
            "- 来源存档 run_id：%s（verdict=%s）" % (s4_case["run_id"], s4_case["verdict"]),
            "- 支持提高关注：%s" % ", ".join(s4_case["support"]) or "无",
            "- 意见相反（提示缓解）：%s" % ", ".join(s4_case["reverse"]) or "无",
            "- 仅支持部分判断（不确定性）：%s" % ", ".join(s4_case["limitation"]) or "无",
            "- 说明：%s" % s4_case["verdict_note"],
        ]
    else:
        lines.append("- 无 S4_with_evidence 存档（可先运行 python B07/S4/run.py --with_evidence）")
    lines += [
        "",
        "## 证据缺失案例（S5 存档，天气 unavailable）",
    ]
    if s5_case:
        lines += [
            "- 来源存档 run_id：%s（fault=%s，verdict=%s）" % (
                s5_case["run_id"], s5_case["fault"], s5_case["verdict"]),
            "- 有效证据：%s" % ", ".join(s5_case["adopted"]),
        ]
        for m in s5_case["missing"]:
            lines.append("- 缺失证据：%s（%s，status=%s）不可用原因：%s" % (
                m["evidence_id"], m["source_type"], m["status"], m["reason"]))
        lines += [
            "- 对判断的影响：%s" % s5_case["verdict_note"],
            "- 区分说明：「没有数据」= 证据标记 unavailable 并如实展示原因与影响，"
            "而不是从页面消失（缺失本身被当作信息呈现）。",
        ]
    else:
        lines.append("- 无 S5_fault(weather_unavailable) 存档（可先运行 python B07/S5/run.py --fault weather_unavailable）")
    lines += [
        "",
        "## 一句话回答",
        "GreenMate 的判断依据全部可追溯：历史（已发生）与模型（推断）支持提高关注；"
        "天气证据在分歧案例中提示缓解、在缺失案例中如实标注不可用；"
        "知识证据只支持部分判断。证据支持、相反、缺失三种状态在空间视图上一目了然。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="VIEW3 证据空间视图（只读渲染）")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="读取的 run_id（默认任务书指定）")
    parser.add_argument("--out", default="VIEW3_REPORT.md", help="md 快照输出文件")
    args = parser.parse_args()

    main_record = load_json(args.run_id, I3_DIR)
    main = extract_main(main_record)
    s4_case = extract_s4_case()
    s5_case = extract_s5_case()
    text = render_md(main, s4_case, s5_case)
    print(text)
    out_path = Path(__file__).resolve().parent / args.out
    out_path.write_text(text, encoding="utf-8")
    print("\n[已写入] %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
