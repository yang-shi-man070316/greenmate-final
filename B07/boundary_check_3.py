"""GreenMate B07 边界检查3：知识证据 ≠ 当前对象诊断事实 边界校验。

核心规则（任务书）：
  找到专业资料 ≠ 得到专家诊断；知识证据 ≠ 当前对象的诊断事实。
  B04 的 RAG 仅用来提供专业文献依据，只能陈述资料里的通用规律，
  不能直接判定当前这株番茄已经出现生理问题，不能输出确定性处置指令。

✅ 合规示例：根据检索到的专业资料，持续高温属于值得关注的环境条件之一；
            展示引用来源，区分「资料描述」和「当前植株情况」。
❌ 违禁语句：当前番茄已经出现生理问题、该植株符合文献描述情况、
            确诊植株问题、直接下定处置指令。

扫描范围：
  - B07/S1~S5 全部 run 存档（json 递归到字段路径）；
  - B07/VIEW 四个视图的 md 报告与 index.html 页面文本（行级定位）。

分级：
  - 违规级：把文献结论当成当前植株确诊事实、确定性处置指令；
  - 提示级：模糊易混淆话术（供审阅 + 改写建议）。

输出：控制台检查结果 + BOUNDARY_CHECK3_REPORT.md（与检查1/2并列于 B07 根目录）。

用法（项目根目录）：
  python B07/boundary_check_3.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

B07_DIR = Path(__file__).resolve().parent
ROOT = B07_DIR.parent
REPORT_FILE = B07_DIR / "BOUNDARY_CHECK3_REPORT.md"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

# 违规级规则：把文献结论当成当前植株确诊事实 / 确定性处置指令
VIOLATION_RULES = [
    {
        "name": "当前植株生理问题判定（知识证据 ≠ 诊断事实，严禁）",
        "patterns": [
            r"已经出现.{0,6}生理问题", r"出现生理问题", r"存在生理问题", r"生理障碍",
            r"生理失调", r"生理异常", r"当前番茄已经", r"当前植株已经",
            r"该植株已经", r"这株番茄已", r"番茄已经", r"番茄已出现",
            r"当前番茄出现", r"当前植株出现",
        ],
        "suggestion": ("删除对当前植株的生理问题判定。B04 资料只能陈述通用规律，如"
                       "「根据检索到的专业资料，持续高温属于值得关注的环境条件之一」，"
                       "并区分「资料描述」与「当前植株情况」。"),
    },
    {
        "name": "当前对象符合文献描述（把通用规律套到当前植株，严禁）",
        "patterns": [
            r"该植株符合", r"符合文献描述", r"与文献描述一致", r"符合.{0,6}文献",
            r"当前植株符合", r"适用于当前", r"该植株适用", r"符合当前情况",
        ],
        "suggestion": ("不得宣称当前植株「符合文献描述」。改为「资料显示（引用来源）……」"
                       "并注明该规律是否适用于当前环境，需进一步观察确认。"),
    },
    {
        "name": "确诊类表述（严禁）",
        "patterns": [r"确诊", r"确诊植株", r"确认植株.{0,4}问题", r"判定植株.{0,4}问题"],
        "suggestion": "删除确诊类表述：系统只能提供环境风险提示，不做植株问题确诊。",
    },
    {
        "name": "确定性处置指令（严禁直接下定处置指令）",
        "patterns": [
            r"必须立即", r"立即执行", r"马上.{0,4}处理", r"立即采取", r"必须.{0,4}处置",
            r"马上处置", r"应当立即", r"必须马上", r"立即处置",
        ],
        "suggestion": ("删除确定性处置指令。改为提醒类文案，如"
                       "「建议进一步检查环境变化」「建议人工确认后采取相应管理措施」。"),
    },
]

# 提示级规则：模糊易混淆话术
INFO_RULES = [
    {
        "name": "「生理问题」一词出现（供审阅，确认属资料通用描述而非当前判定）",
        "patterns": [r"生理问题"],
        "note": "「生理问题」若出现在资料引用（通用规律）中可保留；若用于描述当前植株则违规。",
    },
    {
        "name": "资料与当前植株混述（易混淆，建议拆开表述）",
        "patterns": [r"资料显示当前", r"资料表明当前植株", r"资料.{0,6}当前植株",
                     r"文献显示当前", r"依据资料.{0,4}判定", r"根据文献.{0,4}判定"],
        "note": "「资料显示」应只接通用规律；涉及当前植株的部分单独表述并标注为观察/推断。",
    },
    {
        "name": "处置类词语（供审阅，确认非确定性指令）",
        "patterns": [r"处置方案", r"处置指令", r"处理方案"],
        "note": "「处置方案」等偏指令性表述：建议改为「管理建议」「需关注的环境变化」。",
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
        "# GreenMate B07 边界检查3报告（知识证据 ≠ 当前对象诊断事实）",
        "",
        "- 检查时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 扫描范围：S1~S5 run 存档 %d 个 json | 视图 md 报告 %d 个 | 视图页面 %d 个" % (
            stats["json_files"], stats["md_files"], stats["html_files"]),
        "- 定位说明：json 存档定位到字段路径，md/html 定位到行号",
        "",
        "## 边界规则",
        "",
        "- **找到专业资料 ≠ 得到专家诊断；知识证据 ≠ 当前对象的诊断事实**；",
        "- B04 的 RAG 仅用来提供专业文献依据，只能陈述资料里的通用规律，"
        "不能直接判定当前这株番茄已经出现生理问题，不能输出确定性处置指令；",
        "- 合规示例：「根据检索到的专业资料，持续高温属于值得关注的环境条件之一」"
        "（展示引用来源，区分「资料描述」和「当前植株情况」）；",
        "- 违禁语句：「当前番茄已经出现生理问题」「该植株符合文献描述情况」"
        "「确诊植株问题」「直接下定处置指令」。",
        "",
        "## 违规检查结果",
        "",
    ]
    if violations:
        lines.append("⚠️ 发现 %d 处越界语句：\n" % len(violations))
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
        lines.append("✅ 未发现任何把文献结论当成当前植株确诊事实的语句"
                     "（无生理问题判定/符合文献描述/确诊/确定性处置指令）。\n")
    lines += [
        "## 提示级命中（模糊易混淆话术，供审阅）",
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
        ("✅ 边界检查3通过：所有存档与视图文本中，B04 知识仅作为专业文献依据被引用"
         "（通用规律 + 引用来源），未出现对当前植株的诊断性判定与确定性处置指令。"
         % ()) if not violations else
        ("❌ 边界检查3未通过：发现 %d 处越界语句，请按改写建议改写成合规的资料引用表述。"
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
