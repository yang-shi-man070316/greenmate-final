"""模块2：风险溯源链路可视化（独立后置分析工具，只读）。

复用原有推理归因权重（B07/S4 的 classify_evidence 方向分类，只读 import），
仅展示本次 run 真实获取到的证据，不编造归因。
双格式输出：
1. Markdown 树形文本（stdout 打印 + 可写文件）；
2. 简易静态 HTML 页面（与现有 VIEW 样式统一，内联 CSS、无 JS）。

支持批量处理 B01~B08 存档（--dir）。

用法（项目根目录）：
  python B08/innovate/trace_view/render_trace.py --file <json>
  python B08/innovate/trace_view/render_trace.py --dir <目录> --outdir <输出目录>
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
for d in (ROOT / "B08", ROOT / "B07" / "S5", ROOT / "B07" / "S4", ROOT / "B07" / "S3",
          ROOT / "B07" / "S2", ROOT / "B07" / "S1", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B07.S4.judgment import classify_evidence  # noqa: E402 （复用原有归因分类，只读）

DIRECTION_NAMES = {
    "support_attention": "支持（指向关注）",
    "mitigating_or_reverse": "反向提示（缓解/相反方向）",
    "insufficient": "限制（不确定性）",
}

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def judgment_of(record):
    return (record.get("structured_judgment")
            or record.get("step4_structured_judgment")
            or record.get("judgment") or {})


def extract_evidence(record):
    return record.get("adopted_evidence") or record.get("evidence") or []


def build_trace(record):
    """构建溯源树：run → 证据（归因方向复用 S4 分类）→ 结论。"""
    evidence = extract_evidence(record)
    judgment = judgment_of(record)
    # 归因方向：存档自带 synthesis 优先（不编造），否则复用 S4 分类规则
    synthesis = judgment.get("synthesis")
    direction_map = {}
    if synthesis:
        for part in synthesis:
            for ev in synthesis.get(part) or []:
                direction_map[ev.get("evidence_id")] = part
    if not direction_map and evidence:
        classified = classify_evidence(evidence)
        for part, evs in classified.items():
            for ev in evs:
                direction_map[ev.get("evidence_id")] = part
    return {
        "run_id": record.get("run_id", "未标注"),
        "verdict": judgment.get("verdict", "未存储"),
        "verdict_note": judgment.get("verdict_note") or "",
        "evidence": evidence,
        "direction_map": direction_map,
        "created_at": record.get("created_at", "未存储"),
    }


def render_markdown(trace):
    lines = [
        "## 风险溯源链路：run_id %s" % trace["run_id"],
        "",
        "- 判定：**%s**（%s）" % (trace["verdict"], trace["verdict_note"]),
        "- 创建时间：%s" % trace["created_at"],
        "",
        "```",
        "结论 verdict=%s" % trace["verdict"],
    ]
    if not trace["evidence"]:
        lines.append("└─ （本 run 无证据记录，如实标注）")
    for i, ev in enumerate(trace["evidence"]):
        branch = "└─" if i == len(trace["evidence"]) - 1 else "├─"
        direction = trace["direction_map"].get(ev.get("evidence_id"))
        dir_name = DIRECTION_NAMES.get(direction, "未采用/未分类")
        result = ev.get("result") or {}
        brief = (json.dumps(result, ensure_ascii=False)[:120]
                 if ev.get("status") == "ok" else str(ev.get("error"))[:100])
        lines.append("%s 证据 %s（%s，来源 %s，status=%s）→ 归因：%s" % (
            branch, ev.get("evidence_id", "E?"), ev.get("source_type"),
            ev.get("source", "?"), ev.get("status"), dir_name))
        lines.append("    └─ 内容：%s" % brief)
    lines.append("```")
    lines.append("")
    lines.append("> 归因方向复用原有推理分类（synthesis / S4 classify_evidence），"
                 "仅展示本 run 真实获取到的证据，不编造归因。")
    return "\n".join(lines)


PAGE_CSS = """
  :root { --primary:#b39ddb; --primary-dark:#9575cd; --primary-darker:#7e57c2;
          --bg:#f3effa; --card:#ffffff; --border:#e3ddf0; --text:#332f3d; --muted:#8a8498;
          --ok:#1b7a3d; --warn:#b26a00; --err:#c62828; }
  * { box-sizing:border-box; }
  body { font-family:system-ui,"Microsoft YaHei",sans-serif; background:var(--bg);
         color:var(--text); margin:0; padding:32px 16px; display:flex; justify-content:center; }
  .main-card { width:100%; max-width:860px; background:var(--card); border-radius:16px;
               box-shadow:0 8px 28px rgba(94,74,138,.10); padding:28px 32px 24px; }
  h1 { font-size:20px; margin:0 0 10px; color:var(--primary-darker); }
  .runid-bar { background:var(--bg); border:1px solid var(--border); border-radius:10px;
               padding:10px 14px; font-size:13px; line-height:1.8; margin-bottom:16px; }
  .runid-bar b { color:var(--primary-darker); font-family:Consolas,monospace; }
  .tree { font-size:13px; line-height:1.9; border:1px solid var(--border);
          border-radius:12px; background:#fdfcff; padding:14px 18px; }
  .tree .node { margin-left:0; }
  .tree .ev { margin-left:22px; border-left:2px dashed var(--border); padding-left:12px; }
  .tag { border-radius:999px; padding:1px 10px; font-size:11px; font-weight:600; margin-right:6px; }
  .tag.support { background:#fdeeee; color:var(--err); border:1px solid #f3c0c0; }
  .tag.reverse { background:#e8f1fb; color:#1565c0; border:1px solid #c4ddf5; }
  .tag.limit { background:#fdf3e0; color:var(--warn); border:1px solid #eed9a8; }
  .tag.none { background:var(--bg); color:var(--muted); border:1px solid var(--border); }
  footer { margin-top:18px; font-size:12px; color:var(--muted); line-height:1.7;
           border-top:1px dashed var(--border); padding-top:12px; }
"""


def render_html(trace):
    esc = lambda s: (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    cls = {"support_attention": "support", "mitigating_or_reverse": "reverse",
           "insufficient": "limit"}
    html = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\">",
        "<title>风险溯源链路 %s</title><style>%s</style></head><body>" % (
            esc(trace["run_id"]), PAGE_CSS),
        '<div class="main-card"><h1>风险溯源链路视图</h1>',
        '<div class="runid-bar">run_id: <b>%s</b><br>判定：<b>%s</b>（%s）<br>创建时间：%s</div>'
        % (esc(trace["run_id"]), esc(trace["verdict"]), esc(trace["verdict_note"]),
           esc(trace["created_at"])),
        '<div class="tree"><div class="node">结论 verdict=%s</div>' % esc(trace["verdict"]),
    ]
    if not trace["evidence"]:
        html.append('<div class="ev">（本 run 无证据记录，如实标注）</div>')
    for ev in trace["evidence"]:
        direction = trace["direction_map"].get(ev.get("evidence_id"))
        tag_cls = cls.get(direction, "none")
        dir_name = DIRECTION_NAMES.get(direction, "未采用/未分类")
        result = ev.get("result") or {}
        brief = (json.dumps(result, ensure_ascii=False)[:150]
                 if ev.get("status") == "ok" else str(ev.get("error"))[:100])
        html.append(
            '<div class="ev"><span class="tag %s">%s</span>证据 %s（%s，来源 %s，status=%s）'
            '<br><span style="color:#8a8498">内容：%s</span></div>' % (
                tag_cls, esc(dir_name), esc(ev.get("evidence_id", "E?")),
                esc(ev.get("source_type")), esc(ev.get("source", "?")),
                esc(ev.get("status")), esc(brief)))
    html.append('</div><footer>归因方向复用原有推理分类（synthesis / S4 classify_evidence），'
                '仅展示本 run 真实获取到的证据，不编造归因；纯静态页面，无 JS。</footer>'
                '</div></body></html>')
    return "\n".join(html)


def main():
    parser = argparse.ArgumentParser(description="风险溯源链路可视化（只读批量）")
    parser.add_argument("--file", help="单个 json 存档")
    parser.add_argument("--dir", help="批量处理目录下的 json 存档")
    parser.add_argument("--outdir", help="批量模式输出目录（md + html）")
    args = parser.parse_args()

    paths = []
    if args.file:
        paths = [Path(args.file)]
    elif args.dir:
        paths = sorted(Path(args.dir).glob("*.json"))
    if not paths:
        parser.print_help()
        return 1

    outdir = Path(args.outdir) if args.outdir else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print("%s：文件损坏，无法解析（%s）" % (path.name, e))
            continue
        trace = build_trace(record)
        md = render_markdown(trace)
        html = render_html(trace)
        if outdir:
            stem = path.stem
            (outdir / ("%s_trace.md" % stem)).write_text(md, encoding="utf-8")
            (outdir / ("%s_trace.html" % stem)).write_text(html, encoding="utf-8")
            print("%s → %s_trace.md / %s_trace.html（verdict=%s，证据 %d 条）" % (
                path.name, stem, stem, trace["verdict"], len(trace["evidence"])))
        else:
            print(md)
            print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
