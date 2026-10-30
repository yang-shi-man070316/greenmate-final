"""GreenMate B07 边界检查1：定位与文案边界校验。

GreenMate 定位（任务书）：
  只做番茄生长环境状态分析、时序变化理解、短时趋势预测、辅助判断；
  不做植株病害诊断、产量预测、施肥推荐、设备自动控制。
核心区分：环境风险 ≠ 植株疾病。

文案规范：
  可以写：当前环境状态需要提高关注；当前环境条件可能增加后续管理关注的必要性。
  严禁出现：番茄已经患病、确认发生病害、植株发病这类判定语句。

扫描范围：
  - B07/S1~S5 全部 run 存档（json 递归到字段路径）；
  - B07/VIEW 四个视图的 md 报告与 index.html 页面文本（行级定位）。

输出：控制台检查结果 + BOUNDARY_CHECK1_REPORT.md（违规位置 + 修改建议）。

用法（项目根目录）：
  python B07/boundary_check_1.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

B07_DIR = Path(__file__).resolve().parent
ROOT = B07_DIR.parent
REPORT_FILE = B07_DIR / "BOUNDARY_CHECK1_REPORT.md"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

# 违规级规则：越界下结论的语句（命中即违规）
VIOLATION_RULES = [
    {
        "name": "疾病诊断判定（环境风险 ≠ 植株疾病）",
        "patterns": [r"已经患病", r"确认.{0,6}病害", r"确诊", r"植株发病", r"发病",
                     r"患病", r"患有.{0,6}病", r"感染了", r"染病", r"已经感染",
                     r"生病", r"病症出现"],
        "suggestion": ("改为环境风险描述，如「当前环境条件可能增加后续管理关注的必要性」；"
                       "不得给出植株疾病诊断结论（番茄已经患病/确认发生病害/植株发病等表述禁用）。"),
    },
    {
        "name": "产量预测",
        "patterns": [r"预计产量", r"亩产", r"产量预测", r"增产", r"减产", r"产量将"],
        "suggestion": "删除产量预测内容：GreenMate 只做环境状态分析，不预测产量。",
    },
    {
        "name": "施肥推荐",
        "patterns": [r"建议施肥", r"施肥方案", r"增施", r"追肥", r"推荐.{0,6}施肥"],
        "suggestion": ("改为环境描述，如「当前环境条件不适宜额外农事操作（如施肥），"
                       "建议先改善环境参数」；不给出施肥方案推荐。"),
    },
    {
        "name": "设备自动控制",
        "patterns": [r"已自动", r"自动控制", r"自动开启", r"自动调节", r"自动执行",
                     r"已启动通风", r"自动浇水", r"自动补光"],
        "suggestion": "改为辅助建议，如「建议人工确认后调整环境设备」；GreenMate 不执行设备控制。",
    },
]

# 提示级规则：风险诱因/养护建议描述（非诊断结论，列示供审阅）
INFO_RULES = [
    {
        "name": "疾病风险诱因描述（环境风险说明，可接受）",
        "patterns": [r"霉菌", r"根腐", r"枯萎", r"易诱发"],
        "note": "如「易诱发霉菌与根腐」属环境风险诱因说明，不是疾病诊断结论，符合边界；列入供审阅。",
    },
    {
        "name": "疾病名词单独出现（灰色地带，建议改用环境表述）",
        "patterns": [r"灰霉", r"白粉", r"霜霉", r"疫病", r"叶斑", r"锈病", r"炭疽", r"病害"],
        "note": ("出现具体疾病名词（未下诊断结论但属灰色地带）：建议改写为环境风险描述，"
                 "如「湿度可能上升，需关注叶面结露风险」，去掉疾病名。"),
    },
    {
        "name": "养护建议提及（可接受）",
        "patterns": [r"暂停施肥", r"遮阴", r"浇水", r"通风"],
        "note": "环境管理建议属于辅助判断范围，符合边界；列入供审阅。",
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
        "# GreenMate B07 边界检查1报告",
        "",
        "- 检查时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 扫描范围：S1~S5 run 存档 %d 个 json | 视图 md 报告 %d 个 | 视图页面 %d 个" % (
            stats["json_files"], stats["md_files"], stats["html_files"]),
        "- 定位说明：json 存档定位到字段路径（如 llm_explanation.answer），md/html 定位到行号",
        "",
        "## 边界规则",
        "",
        "- GreenMate 只做：番茄生长环境状态分析、时序变化理解、短时趋势预测、辅助判断；",
        "- 不做：植株病害诊断、产量预测、施肥推荐、设备自动控制；",
        "- 核心区分：**环境风险 ≠ 植株疾病**；",
        "- 可以写：「当前环境状态需要提高关注」「当前环境条件可能增加后续管理关注的必要性」；",
        "- 严禁出现：「番茄已经患病」「确认发生病害」「植株发病」等判定语句。",
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
                lines.append("  修改建议：%s" % h["suggestion"])
            lines.append("")
    else:
        lines.append("✅ 未发现任何越界语句（无疾病诊断判定、产量预测、施肥推荐、设备自动控制）。\n")
    lines += [
        "## 提示级命中（风险诱因/养护建议描述，供审阅）",
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
        ("✅ 边界检查通过：所有存档与视图文本均在 GreenMate 定位范围内，"
         "未出现越界下结论（植株疾病诊断/产量预测/施肥推荐/设备自动控制）。"
         % ()) if not violations else
        ("❌ 边界检查未通过：发现 %d 处越界语句，请按上方修改建议改写成合规的环境风险描述。"
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
