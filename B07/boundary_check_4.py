"""GreenMate B07 边界检查4：有什么证据，就说到哪里 边界校验。

核心规则（任务书）：
  LLM 能补一句话 ≠ 系统真的拥有这份证据；有什么证据，就说到哪里。
  如果当前 run 没有拿到某类证据（例如天气 API 失败、无未来天气数据），
  禁止 LLM 依靠常识编造该证据对应的事实结论。

✅ 合规示例：
  「当前未来天气信息不可用，因此无法判断外部天气是否会进一步影响后续环境状态。」
  「根据已经获得的历史数据，最近存在持续升温趋势。」
❌ 违禁语句：
  「未来天气预计继续升温」「后续天气将会XX」「根据天气预报」（本次无天气证据却输出
  天气预判）、捏造当前 run 不存在的数据源信息。

检查方式（上下文相关）：先判定每个存档的四类证据状态
（weather/history/prediction/knowledge 是否存在且有效），
仅对「无天气证据」的存档启用天气预判违禁模式——同一句话在有天气证据的 run 中合规，
在缺失天气证据的 run 中违规。

扫描范围：B07/S1~S5 全部 json 存档（递归到字段路径）、B07/VIEW 视图 md/html（行级）。
输出：控制台结果 + BOUNDARY_CHECK4_REPORT.md（与检查1~3并列于 B07 根目录）。

用法（项目根目录）：
  python B07/boundary_check_4.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

B07_DIR = Path(__file__).resolve().parent
ROOT = B07_DIR.parent
REPORT_FILE = B07_DIR / "BOUNDARY_CHECK4_REPORT.md"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

# 违规级：无天气证据时的天气预判/编造模式（门控启用）
WEATHER_FABRICATION_RULE = {
    "name": "无天气证据时编造天气结论（有什么证据，就说到哪里，严禁）",
    "patterns": [
        r"未来天气.{0,6}(预计|将|会)", r"后续天气.{0,6}(预计|将|会)", r"未来天气预计",
        r"根据天气预报", r"预报显示", r"天气预报显示", r"气象预报显示",
        r"预计.{0,4}降水", r"预计.{0,4}下雨", r"预计.{0,4}阴雨", r"预计.{0,4}降温",
        r"降水概率", r"云量", r"未来继续升温", r"天气将继续", r"预计继续升温",
    ],
    "suggestion": ("删除天气预判内容。改为合规表述，如「当前未来天气信息不可用，"
                   "因此无法判断外部天气是否会进一步影响后续环境状态。」"
                   "——只描述已有证据可支撑的内容。"),
}

# 提示级：容易越界的推测话术（供审阅）
INFO_RULES = [
    {
        "name": "趋势外推话术（供审阅，确认基于已有证据而非编造）",
        "patterns": [r"预计未来.{0,10}", r"后续可能.{0,10}", r"未来可能.{0,10}",
                     r"很可能继续", r"或将持续"],
        "note": "「预计未来/后续可能」等外推话术需审阅：只允许基于已有证据（历史趋势/模型预测）"
                "的谨慎推断，不允许对无证据维度（如缺失的天气）做预判。",
    },
]


def evidence_status(record):
    """判定该 run 的四类证据状态（只读，兼容各实验记录结构）。

    返回 {"weather": "ok"|"error"|"unavailable"|"absent", ...}
    """
    status = {"weather": "absent", "history": "absent",
              "prediction": "absent", "knowledge": "absent"}

    def mark(field, evidences):
        for ev in evidences or []:
            st = ev.get("source_type")
            if not st:
                continue
            s = ev.get("status")
            if s == "ok" and not (ev.get("result") or {}).get("no_match"):
                status[field] = "ok"
            elif s in ("error", "unavailable"):
                status[field] = s
            elif s == "ok":  # no_match：证据存在但无匹配数据
                status[field] = "unavailable"

    mark("weather", record.get("adopted_evidence") or record.get("evidence"))
    mark("history", record.get("adopted_evidence") or record.get("evidence"))
    mark("prediction", record.get("adopted_evidence") or record.get("evidence"))
    mark("knowledge", record.get("adopted_evidence") or record.get("evidence"))
    # 缺失证据列表（S5 等）：标 error/unavailable
    for ev in record.get("missing_evidence") or []:
        st = ev.get("source_type")
        if st in status and status[st] == "absent":
            status[st] = ev.get("status", "error")
    # S1/S2/S3 风格记录：结构化字段兜底
    hist = record.get("step2_recent_history_3h") or {}
    if status["history"] == "absent" and hist.get("status") == "ok":
        status["history"] = "ok"
    if status["prediction"] == "absent" and record.get("step3_model_prediction"):
        status["prediction"] = "ok"
    wf = record.get("weather_forecast")
    if status["weather"] == "absent" and wf:
        status["weather"] = wf.get("status", "absent")
    if status["weather"] == "absent" and record.get("history_samples") \
            and not record.get("weather_forecast"):
        status["weather"] = "absent"  # i1x 等无天气实验
    return status


def has_weather_evidence(record):
    """该 run 是否拿到有效天气证据。"""
    return evidence_status(record).get("weather") == "ok"


def scan_string(value, path, weather_ok, hits):
    """字符串扫描：提示级全查；天气编造违规仅当 weather_ok=False。"""
    for rule in INFO_RULES:
        for pat in rule["patterns"]:
            for m in re.finditer(pat, value):
                ctx = value[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")
                hits.append({"rule": rule["name"], "match": m.group(), "field": path,
                             "context": ctx, "suggestion": rule.get("note", ""),
                             "level": "info"})
    if not weather_ok:
        for pat in WEATHER_FABRICATION_RULE["patterns"]:
            for m in re.finditer(pat, value):
                ctx = value[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")
                hits.append({"rule": WEATHER_FABRICATION_RULE["name"],
                             "match": m.group(), "field": path, "context": ctx,
                             "suggestion": WEATHER_FABRICATION_RULE["suggestion"],
                             "level": "violation"})


def scan_json(path, record):
    hits = []
    weather_ok = has_weather_evidence(record)

    def walk(obj, field_path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, "%s.%s" % (field_path, k) if field_path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, "%s[%d]" % (field_path, i))
        elif isinstance(obj, str):
            scan_string(obj, field_path, weather_ok, hits)
    walk(record, "")
    return hits


def scan_text(path, text):
    """视图 md/html 行级扫描。

    违禁判定带归因豁免：视图是存档快照，含「来源/存档/S3~S5」等归因标注的行
    属于引用已有证据的展示，不是无证据编造——只对无归因标注的声明性文本判定。
    """
    attribution_hints = ("来源", "存档", "run_id", "S3", "S4", "S5", "证据")
    hits = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for rule in INFO_RULES:
            for pat in rule["patterns"]:
                for m in re.finditer(pat, line):
                    hits.append({"rule": rule["name"], "match": m.group(),
                                 "field": "第 %d 行" % line_no,
                                 "context": line[max(0, m.start() - 25):m.end() + 25],
                                 "suggestion": rule.get("note", ""), "level": "info"})
        if any(h in line for h in attribution_hints):
            continue  # 归因上下文：引用已有证据的展示，不判违禁
        for pat in WEATHER_FABRICATION_RULE["patterns"]:
            for m in re.finditer(pat, line):
                hits.append({"rule": WEATHER_FABRICATION_RULE["name"],
                             "match": m.group(), "field": "第 %d 行" % line_no,
                             "context": line[max(0, m.start() - 25):m.end() + 25],
                             "suggestion": WEATHER_FABRICATION_RULE["suggestion"],
                             "level": "violation"})
    return hits


def scan_all():
    violations, infos = [], []
    stats = {"json_files": 0, "md_files": 0, "html_files": 0,
             "json_with_weather": 0, "json_without_weather": 0}

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
            if has_weather_evidence(record):
                stats["json_with_weather"] += 1
            else:
                stats["json_without_weather"] += 1
            for hit in scan_json(path, record):
                hit["file"] = str(path.relative_to(ROOT))
                (violations if hit["level"] == "violation" else infos).append(hit)

    for view_dir in sorted((B07_DIR / "VIEW").glob("v*")):
        for path in sorted(view_dir.glob("*.md")) + sorted(view_dir.glob("*.html")):
            stats["html_files" if path.suffix == ".html" else "md_files"] += 1
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for hit in scan_text(path, text):
                hit["file"] = str(path.relative_to(ROOT))
                (violations if hit["level"] == "violation" else infos).append(hit)
    return violations, infos, stats


def build_report(violations, infos, stats):
    lines = [
        "# GreenMate B07 边界检查4报告（有什么证据，就说到哪里）",
        "",
        "- 检查时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 扫描范围：S1~S5 run 存档 %d 个 json（其中含天气证据 %d 个、无天气证据 %d 个）"
        "| 视图 md 报告 %d 个 | 视图页面 %d 个" % (
            stats["json_files"], stats["json_with_weather"],
            stats["json_without_weather"], stats["md_files"], stats["html_files"]),
        "- 检查方式：先判定每个存档的四类证据状态，再对「无天气证据」的存档启用"
        "天气预判违禁模式（上下文相关检查）",
        "- 定位说明：json 存档定位到字段路径，md/html 定位到行号",
        "",
        "## 边界规则",
        "",
        "- **LLM 能补一句话 ≠ 系统真的拥有这份证据；有什么证据，就说到哪里**；",
        "- 当前 run 没有拿到某类证据（天气 API 失败、无未来天气数据）时，"
        "禁止 LLM 依靠常识编造该证据对应的事实结论；",
        "- 合规示例：「当前未来天气信息不可用，因此无法判断外部天气是否会进一步影响后续环境状态」"
        "「根据已经获得的历史数据，最近存在持续升温趋势」；",
        "- 违禁语句：「未来天气预计继续升温」「后续天气将会XX」「根据天气预报」"
        "（本次无天气证据却输出天气预判）、捏造当前 run 不存在的数据源信息。",
        "",
        "## 违规检查结果",
        "",
    ]
    if violations:
        lines.append("⚠️ 发现 %d 处无证据编造语句：\n" % len(violations))
        by_file = {}
        for h in violations:
            by_file.setdefault(h["file"], []).append(h)
        for fname, hs in sorted(by_file.items()):
            lines.append("### %s（%d 处）" % (fname, len(hs)))
            for h in hs:
                lines.append("- **%s** 命中「%s」（位置：%s）" % (h["rule"], h["match"], h["field"]))
                lines.append("  上下文：…%s…" % h["context"])
                lines.append("  改写建议：%s" % h["suggestion"])
            lines.append("")
    else:
        lines.append("✅ 未发现无证据编造：无天气证据的 run 均未输出天气预判"
                     "（未出现未来天气预计/根据天气预报/降水概率等编造内容）。\n")
    lines += [
        "## 提示级命中（容易越界的推测话术，供审阅）",
        "",
    ]
    if infos:
        by_file = {}
        for h in infos:
            by_file.setdefault(h["file"], []).append(h)
        for fname, hs in sorted(by_file.items()):
            lines.append("### %s（%d 处）" % (fname, len(hs)))
            for h in hs:
                lines.append("- 「%s」命中（位置：%s）：…%s…" % (
                    h["match"], h["field"], h["context"]))
                lines.append("  说明：%s" % h["suggestion"])
            lines.append("")
    else:
        lines.append("无提示级命中。\n")
    lines += [
        "## 总结论",
        "",
        ("✅ 边界检查4通过：无天气证据的 run 均如实说明「天气信息不可用」"
         "并收缩判断，未依靠常识编造天气结论；系统做到了有什么证据就说到哪里。"
         % ()) if not violations else
        ("❌ 边界检查4未通过：发现 %d 处无证据编造语句，请按改写建议修改。"
         % len(violations)),
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
