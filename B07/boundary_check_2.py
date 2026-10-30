"""GreenMate B07 边界检查2：预测 ≠ 控制 边界校验。

规则（任务书）：
  WATCH 预警只是预测证据，不是自动控制指令——预测 ≠ 控制。
  允许文案：提醒用户下一时间段值得关注；给出需要进一步检查的环境变化。
  违禁文案：自动灌溉、自动施肥、自动通风、自动开启设备、执行控制、触发设备动作
  等一切自动控制相关语句。

扫描范围：
  - B07/S1~S5 全部 run 存档（json 递归到字段路径）；
  - B07/VIEW 四个视图的 md 报告与 index.html 页面文本（行级定位）。

分级：
  - 违规级：自动控制动作描述（自动灌溉/自动通风/执行控制/触发设备动作等）；
  - 提示级：容易混淆的话术（启动通风/通风系统等，建议改人工表述）。

输出：控制台检查结果 + BOUNDARY_CHECK2_REPORT.md（文件、行号/字段路径、上下文、改写建议）。

用法（项目根目录）：
  python B07/boundary_check_2.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

B07_DIR = Path(__file__).resolve().parent
ROOT = B07_DIR.parent
REPORT_FILE = B07_DIR / "BOUNDARY_CHECK2_REPORT.md"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

# 违规级规则：自动控制动作描述（命中即违规）
VIOLATION_RULES = [
    {
        "name": "自动控制动作描述（预测 ≠ 控制，严禁）",
        "patterns": [
            r"自动灌溉", r"自动施肥", r"自动通风", r"自动浇水", r"自动补光",
            r"自动遮阴", r"自动降温", r"自动加湿", r"自动喷雾", r"自动排风",
            r"自动开启", r"自动关闭", r"自动启动", r"自动停止", r"自动执行",
            r"自动控制", r"自动调节", r"自动触发", r"自动切换", r"自动干预",
            r"系统将自动", r"系统会自动", r"将自动执行",
        ],
        "suggestion": ("删除自动控制动作描述。WATCH 只是预测证据，只能写提醒类文案，如"
                       "「下一时间段值得关注」「建议进一步检查环境变化」「建议人工确认后调整环境设备」。"),
    },
    {
        "name": "设备动作执行描述（严禁）",
        "patterns": [
            r"触发设备", r"触发.{0,4}动作", r"执行控制", r"下达控制", r"控制设备",
            r"操控设备", r"设备动作", r"启动设备", r"开启设备", r"关闭设备",
            r"已启动通风", r"已开启补光", r"已触发", r"已自动",
        ],
        "suggestion": ("删除设备动作描述。系统不执行任何设备动作；如确需提醒，改为"
                       "「建议人工确认后调整环境设备」。"),
    },
]

# 提示级规则：容易混淆的话术（列示供审阅 + 改写建议）
INFO_RULES = [
    {
        "name": "动作类话术（建议改人工表述）",
        "patterns": [r"启动通风", r"开启通风", r"打开通风", r"启动灌溉", r"开启灌溉",
                     r"启动遮阴", r"启动加湿", r"启动补光"],
        "note": "「启动通风」等偏设备动作执行：建议改写为「建议人工加强通风」等人工操作建议。",
    },
    {
        "name": "设备系统名词（建议改条件表述）",
        "patterns": [r"通风系统", r"灌溉系统", r"补光系统", r"降温系统", r"加湿系统"],
        "note": "设备系统名词容易暗示自动控制：建议改写为「通风条件」「光照条件」等环境表述。",
    },
    {
        "name": "「自动」一词出现（供审阅，确认非自动控制语境）",
        "patterns": [r"自动"],
        "note": "出现「自动」一词：需人工审阅确认非自动控制语境（如为预测说明可保留）。",
    },
]


def scan_string(value, path, rule_set, hits):
    """对单个字符串值应用规则集，命中记录字段路径与上下文。"""
    for rule in rule_set:
        for pat in rule["patterns"]:
            for m in re.finditer(pat, value):
                ctx = value[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")
                hits.append({
                    "rule": rule["name"],
                    "match": m.group(),
                    "field": path,
                    "context": ctx,
                    "suggestion": rule.get("suggestion", rule.get("note", "")),
                })


def scan_json(path, record):
    """递归扫描 json 存档（定位到字段路径）。"""
    hits = []

    def walk(obj, field_path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, "%s.%s" % (field_path, k) if field_path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, "%s[%d]" % (field_path, i))
        elif isinstance(obj, str):
            scan_string(obj, field_path, VIOLATION_RULES + INFO_RULES, hits)
    walk(record, "")
    return hits


def scan_text(path, text):
    """扫描 md/html 文本（定位到行号）。"""
    hits = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for rule in VIOLATION_RULES + INFO_RULES:
            for pat in rule["patterns"]:
                for m in re.finditer(pat, line):
                    ctx = line[max(0, m.start() - 25):m.end() + 25]
                    hits.append({
                        "rule": rule["name"],
                        "match": m.group(),
                        "field": "第 %d 行" % line_no,
                        "context": ctx,
                        "suggestion": rule.get("suggestion", rule.get("note", "")),
                    })
    return hits


def scan_all():
    """扫描 S1~S5 存档 + VIEW 视图文件，返回 (violations, infos, stats)。"""
    violations, infos = [], []
    stats = {"json_files": 0, "md_files": 0, "html_files": 0}

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
            for hit in scan_json(path, record):
                hit["file"] = str(path.relative_to(ROOT))
                (violations if _is_violation(hit) else infos).append(hit)

    for view_dir in sorted((B07_DIR / "VIEW").glob("v*")):
        for path in sorted(view_dir.glob("*.md")) + sorted(view_dir.glob("*.html")):
            stats["html_files" if path.suffix == ".html" else "md_files"] += 1
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for hit in scan_text(path, text):
                hit["file"] = str(path.relative_to(ROOT))
                (violations if _is_violation(hit) else infos).append(hit)
    return violations, infos, stats


def _is_violation(hit):
    return any(r["name"] == hit["rule"] for r in VIOLATION_RULES)


def build_report(violations, infos, stats):
    lines = [
        "# GreenMate B07 边界检查2报告（预测 ≠ 控制）",
        "",
        "- 检查时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 扫描范围：S1~S5 run 存档 %d 个 json | 视图 md 报告 %d 个 | 视图页面 %d 个" % (
            stats["json_files"], stats["md_files"], stats["html_files"]),
        "- 定位说明：json 存档定位到字段路径，md/html 定位到行号",
        "",
        "## 边界规则",
        "",
        "- **预测 ≠ 控制**：WATCH 预警只是预测证据，不是自动控制指令；",
        "- 允许文案：「提醒用户下一时间段值得关注」「给出需要进一步检查的环境变化」；",
        "- 违禁文案：「自动灌溉」「自动施肥」「自动通风」「自动开启设备」「执行控制」"
        "「触发设备动作」等一切自动控制相关语句；",
        "- 所有视图、LLM 输出文本只做提示告知，绝不生成自动执行设备动作的描述。",
        "",
        "## 违规检查结果",
        "",
    ]
    if violations:
        lines.append("⚠️ 发现 %d 处自动控制相关语句：\n" % len(violations))
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
        lines.append("✅ 未发现任何自动控制动作描述（无自动灌溉/自动通风/执行控制/触发设备动作等）。\n")
    lines += [
        "## 提示级命中（容易混淆的话术，供审阅）",
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
        ("✅ 边界检查2通过：所有存档与视图文本只做提示告知，"
         "未出现自动控制动作描述（预测与控制的边界清晰）。"
         % ()) if not violations else
        ("❌ 边界检查2未通过：发现 %d 处自动控制相关语句，请按改写建议删除/改写。"
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
