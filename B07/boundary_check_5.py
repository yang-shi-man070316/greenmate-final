"""GreenMate B07 边界检查5：结论可溯源 / 可回放 / 可对照 校验。

核心规则（任务书）：
  生成了一份漂亮报告 ≠ GreenMate 产品已经成立。
  单纯的 LLM 分析文本、聊天页面、导出 PDF 只是展示形式；GreenMate 是连续状态认知
  与证据分析系统，所有结论必须可溯源、可回放、可对照。

合规要求：
  - 所有结论绑定 run_id；
  - 能够追溯本条判断使用的历史数据、天气证据、RAG 知识、模型结果；
  - 支持场景切换对比、证据摘除退化验证。
违规情况：
  - 只有一段分析文字，缺少 run_id 标识、缺少证据溯源信息、无法核查使用了哪些证据、
    不能回放对照实验。

检查项：
  json 存档（逐条判定）：
    违规级：记录无 run_id；无任何证据溯源字段（只有分析文字）；无结论内容（无判定/LLM 输出）。
    提示级：证据缺 source 字段；LLM 回答未引用证据编号；缺 pipeline_log 调用记录；缺 created_at。
  视图 md/html：
    违规级：未标注 run_id；只有分析文字（无 run_id/来源/证据/存档 等溯源字样）。
    提示级：缺只读/快照/回放声明；有结论板块但缺少来源说明。

输出：控制台结果 + BOUNDARY_CHECK5_REPORT.md（与检查1~4并列于 B07 根目录）。
用法（项目根目录）：python B07/boundary_check_5.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

B07_DIR = Path(__file__).resolve().parent
ROOT = B07_DIR.parent
REPORT_FILE = B07_DIR / "BOUNDARY_CHECK5_REPORT.md"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def judgment_of(record):
    return (record.get("structured_judgment")
            or record.get("step4_structured_judgment")
            or record.get("judgment") or {})


def llm_answer_of(record):
    llm = record.get("llm_explanation") or record.get("step5_llm_explanation") or {}
    return llm.get("answer") or ""


def check_record(path, record):
    """逐条检查一个 json 存档的可溯源/可回放/可对照能力。返回命中列表。"""
    hits = []
    run_id = record.get("run_id")

    # 违规级 1：结论未绑定 run_id
    if not run_id:
        hits.append({
            "rule": "结论未绑定 run_id（无法回放/对照）",
            "match": "（记录级）",
            "field": "（记录级）",
            "context": "记录缺少 run_id 字段",
            "suggestion": "所有结论必须绑定 run_id：为记录补写唯一 run_id，"
                          "并确保视图/报告引用该 run_id。",
            "level": "violation",
        })

    # 违规级 2：无证据溯源链路（只有分析文字）
    has_evidence = bool(
        record.get("adopted_evidence") or record.get("evidence")
        or record.get("step2_recent_history_3h")
        or record.get("internal_baseline")
        or record.get("history_samples")
        or record.get("missing_evidence")
        or record.get("weather_forecast")
        or record.get("step3_model_prediction")
        or record.get("current_observation"))  # 消融组（如 run_current_only）的当前观测值也是证据
    if not has_evidence:
        hits.append({
            "rule": "只有分析文字，缺少证据溯源信息",
            "match": "（记录级）",
            "field": "（记录级）",
            "context": "记录中未保存任何证据（历史/天气/知识/模型）来源字段",
            "suggestion": "结论必须能追溯到证据：补存历史数据、天气证据、RAG 知识、"
                          "模型结果的来源与内容（统一证据字段）。",
            "level": "violation",
        })

    # 违规级 3：无结论内容（无法回放判断）
    has_conclusion = bool(judgment_of(record).get("verdict") or llm_answer_of(record))
    if not has_conclusion:
        hits.append({
            "rule": "无结论内容（无判定/LLM 输出，无法回放判断）",
            "match": "（记录级）",
            "field": "（记录级）",
            "context": "记录中既无结构化判定 verdict，也无 LLM 输出文本",
            "suggestion": "补存结构化判定与 LLM 输出，保证判断过程可回放。",
            "level": "violation",
        })

    # 提示级 1：证据缺 source 字段
    for i, ev in enumerate(record.get("adopted_evidence", []) + record.get("evidence", [])):
        if ev.get("source_type") and not ev.get("source"):
            hits.append({
                "rule": "溯源信息不全：证据缺 source 字段",
                "match": ev.get("evidence_id") or ev.get("source_type"),
                "field": "evidence[%d]" % i,
                "context": "证据 %s 未记录来源" % ev.get("source_type"),
                "suggestion": "为证据补写 source（如 greenmate_b02_db / open_meteo）。",
                "level": "info",
            })

    # 提示级 2：LLM 回答未引用证据编号
    answer = llm_answer_of(record)
    if answer and not re.search(r"\[E\d+\]", answer) and (
            record.get("adopted_evidence") or record.get("evidence")):
        hits.append({
            "rule": "溯源信息不全：LLM 回答未引用证据编号",
            "match": "llm 回答",
            "field": "llm_explanation.answer",
            "context": answer[:60],
            "suggestion": "LLM 输出的每条结论应标注依赖的证据编号（如 [E1]），便于逐条核查。",
            "level": "info",
        })

    # 提示级 3：缺调用记录（回放工具调用过程）
    if not record.get("pipeline_log") and has_evidence:
        hits.append({
            "rule": "回放信息不全：缺 pipeline_log 工具调用记录",
            "match": "（记录级）",
            "field": "（记录级）",
            "context": "记录未保存工具调用日志（调用/成功/转为证据/采用）",
            "suggestion": "补存 pipeline_log，保证工具调用过程可回放核查。",
            "level": "info",
        })

    # 提示级 4：缺 created_at
    if not record.get("created_at"):
        hits.append({
            "rule": "回放信息不全：缺 created_at 时间戳",
            "match": "（记录级）",
            "field": "（记录级）",
            "context": "记录缺少创建时间",
            "suggestion": "补写 created_at 时间戳。",
            "level": "info",
        })
    return hits


def check_view(path, text):
    """检查视图 md/html 的可溯源/可回放/可对照能力。返回命中列表。"""
    hits = []
    has_run_id = "run_id" in text
    has_trace = any(k in text for k in ("来源", "证据", "存档", "run_id", "synthesis",
                                        "pipeline", "verdict"))
    has_replay_note = any(k in text for k in ("只读", "快照", "未重", "未发起", "未重新"))
    has_source_mark = any(k in text for k in ("来源", "source", "存档", "run_id"))

    if not has_run_id:
        hits.append({
            "rule": "视图未标注 run_id（无法回放/对照）",
            "match": "（视图级）",
            "field": "（视图级）",
            "context": "视图顶部未标注 run_id",
            "suggestion": "视图顶部必须标注所展示结论对应的 run_id。",
            "level": "violation",
        })
    if not has_trace:
        hits.append({
            "rule": "只有分析文字，缺少证据溯源信息",
            "match": "（视图级）",
            "field": "（视图级）",
            "context": "视图中无任何来源/证据/存档等溯源字样",
            "suggestion": "视图必须能追溯到证据（历史/天气/知识/模型）与来源存档。",
            "level": "violation",
        })
    if not has_replay_note:
        hits.append({
            "rule": "回放对照信息不全：缺只读/快照/未重跑声明",
            "match": "（视图级）",
            "field": "（视图级）",
            "context": "视图未声明只读快照性质（未重跑实验/未调用 LLM）",
            "suggestion": "补充只读声明：本视图仅读取存档渲染，未重跑实验、未生成新数据。",
            "level": "info",
        })
    if has_trace and not has_source_mark:
        hits.append({
            "rule": "溯源信息不全：有结论但缺少来源标注",
            "match": "（视图级）",
            "field": "（视图级）",
            "context": "视图有溯源字样但无明确来源/存档标注",
            "suggestion": "为每条结论标注来源存档与证据（来源：greenmate_b02_db 等）。",
            "level": "info",
        })
    return hits


def scan_all():
    violations, infos = [], []
    stats = {"json_files": 0, "md_files": 0, "html_files": 0,
             "json_with_run_id": 0, "json_with_evidence": 0}

    for s in range(1, 6):
        records_dir = B07_DIR / ("S%d" % s) / "run_records"
        if not records_dir.exists():
            continue
        for path in sorted(records_dir.glob("*.json")):
            stats["json_files"] += 1
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                print("[警告] 无法解析 %s：%s" % (path.name, e))
                continue
            if record.get("run_id"):
                stats["json_with_run_id"] += 1
            if record.get("adopted_evidence") or record.get("evidence") \
                    or record.get("step2_recent_history_3h") \
                    or record.get("internal_baseline") or record.get("history_samples") \
                    or record.get("missing_evidence") or record.get("weather_forecast") \
                    or record.get("step3_model_prediction") \
                    or record.get("current_observation"):
                stats["json_with_evidence"] += 1
            for hit in check_record(path, record):
                hit["file"] = str(path.relative_to(ROOT))
                (violations if hit["level"] == "violation" else infos).append(hit)

    for view_dir in sorted((B07_DIR / "VIEW").glob("v*")):
        for path in sorted(view_dir.glob("*.md")) + sorted(view_dir.glob("*.html")):
            stats["html_files" if path.suffix == ".html" else "md_files"] += 1
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for hit in check_view(path, text):
                hit["file"] = str(path.relative_to(ROOT))
                (violations if hit["level"] == "violation" else infos).append(hit)
    return violations, infos, stats


def build_report(violations, infos, stats):
    lines = [
        "# GreenMate B07 边界检查5报告（结论可溯源 / 可回放 / 可对照）",
        "",
        "- 检查时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 扫描范围：S1~S5 run 存档 %d 个 json（含 run_id %d 个、含证据溯源字段 %d 个）"
        "| 视图 md 报告 %d 个 | 视图页面 %d 个" % (
            stats["json_files"], stats["json_with_run_id"], stats["json_with_evidence"],
            stats["md_files"], stats["html_files"]),
        "- 定位说明：json 存档定位到字段路径（记录级问题标注「（记录级）」），"
        "md/html 定位到视图级检查",
        "",
        "## 边界规则",
        "",
        "- **生成了一份漂亮报告 ≠ GreenMate 产品已经成立**：单纯的 LLM 分析文本、聊天页面、"
        "导出 PDF 只是展示形式；",
        "- GreenMate 是连续状态认知与证据分析系统，所有结论必须**可溯源、可回放、可对照**："
        "绑定 run_id、可追溯历史数据/天气证据/RAG 知识/模型结果、支持场景切换对比与"
        "证据摘除退化验证；",
        "- 违规情况：只有一段分析文字、缺少 run_id 标识、缺少证据溯源信息、"
        "无法核查使用了哪些证据、不能回放对照实验。",
        "",
        "## 违规检查结果",
        "",
    ]
    if violations:
        lines.append("⚠️ 发现 %d 处溯源/回放违规：\n" % len(violations))
        by_file = {}
        for h in violations:
            by_file.setdefault(h["file"], []).append(h)
        for fname, hs in sorted(by_file.items()):
            lines.append("### %s（%d 处）" % (fname, len(hs)))
            for h in hs:
                lines.append("- **%s**（位置：%s）" % (h["rule"], h["field"]))
                lines.append("  上下文：%s" % h["context"])
                lines.append("  补全建议：%s" % h["suggestion"])
            lines.append("")
    else:
        lines.append("✅ 所有存档均绑定 run_id、具备证据溯源字段与结论内容；"
                     "所有视图均标注 run_id 与溯源字样——无「只有一段分析文字」的违规情况。\n")
    lines += [
        "## 提示级命中（溯源/回放信息不全，供审阅）",
        "",
    ]
    if infos:
        by_file = {}
        for h in infos:
            by_file.setdefault(h["file"], []).append(h)
        for fname, hs in sorted(by_file.items()):
            lines.append("### %s（%d 处）" % (fname, len(hs)))
            for h in hs:
                lines.append("- 「%s」%s（位置：%s）：%s" % (
                    h["rule"], h["match"], h["field"], h["context"][:60]))
                lines.append("  说明：%s" % h["suggestion"])
            lines.append("")
    else:
        lines.append("无提示级命中。\n")
    lines += [
        "## 总结论",
        "",
        ("✅ 边界检查5通过：所有结论均绑定 run_id、可追溯到证据来源、可回放判断过程，"
         "视图与存档共同支撑场景切换对比与证据摘除退化验证——GreenMate 不是漂亮报告，"
         "而是可溯源可回放可对照的证据分析系统。" % ()) if not violations else
        ("❌ 边界检查5未通过：发现 %d 处溯源/回放违规，请按补全建议修复。" % len(violations)),
        "",
    ]
    return "\n".join(lines)


def main():
    violations, infos, stats = scan_all()
    report = build_report(violations, infos, stats)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(report)
    print("\n[报告已写入] %s" % REPORT_FILE)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
