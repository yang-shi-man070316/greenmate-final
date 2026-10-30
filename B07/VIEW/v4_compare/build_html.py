"""VIEW4 静态页面生成器：读取 VIEW4_REPORT.md → 生成 index.html（对照卡片）。

只读规则：只读当前目录 md 快照；纯静态 HTML（内联 CSS，无 JS、无网络请求）；
内容与 md 快照逐条一致（自动校验）。

用法（项目根目录）：
  python B07/VIEW/v4_compare/build_html.py
生成：B07/VIEW/v4_compare/index.html（双击浏览器打开）
"""

import html as html_mod
import re
import sys
from pathlib import Path

VIEW_DIR = Path(__file__).resolve().parent
MD_FILE = VIEW_DIR / "VIEW4_REPORT.md"
HTML_FILE = VIEW_DIR / "index.html"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE_CSS = """
  :root {
    --primary: #b39ddb; --primary-dark: #9575cd; --primary-darker: #7e57c2;
    --bg: #f3effa; --card: #ffffff; --border: #e3ddf0; --text: #332f3d; --muted: #8a8498;
    --ok: #1b7a3d; --warn: #b26a00; --err: #c62828;
  }
  * { box-sizing: border-box; }
  body { font-family: system-ui, "Microsoft YaHei", sans-serif; background: var(--bg);
         color: var(--text); margin: 0; padding: 32px 16px; display: flex; justify-content: center; }
  .main-card { width: 100%; max-width: 920px; background: var(--card); border-radius: 16px;
               box-shadow: 0 8px 28px rgba(94,74,138,0.10); padding: 28px 32px 24px; }
  h1 { font-size: 22px; margin: 0 0 10px; color: var(--primary-darker); }
  h2 { font-size: 15px; margin: 24px 0 12px; color: var(--primary-darker);
       border-left: 4px solid var(--primary); padding-left: 10px; }
  .answer-box { border: 1px solid var(--primary); border-radius: 12px; background: #faf7ff;
                padding: 14px 16px; font-size: 14px; line-height: 1.8; margin-bottom: 20px; }
  .cmp-card { border: 1px solid var(--border); border-radius: 12px; background: #fdfcff;
              padding: 16px 18px; margin-bottom: 16px; }
  .cmp-title { font-weight: 600; font-size: 14px; color: var(--primary-darker); margin-bottom: 10px; }
  .run-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
  .run-chip { border: 1px solid var(--border); border-radius: 10px; background: #fbfaff;
              padding: 8px 12px; font-size: 12px; }
  .run-chip .scene { font-weight: 700; color: var(--primary-darker); margin-right: 6px; }
  .run-chip .rid { font-family: Consolas, monospace; font-size: 11px; color: var(--muted); }
  .tag { border-radius: 999px; padding: 1px 10px; font-size: 11px; font-weight: 600;
         margin-left: 6px; }
  .tag.stable { background: #e6f4ea; color: var(--ok); border: 1px solid #b7dfc2; }
  .tag.attention { background: #fdeeee; color: var(--err); border: 1px solid #f3c0c0; }
  .tag.other { background: #fdf3e0; color: var(--warn); border: 1px solid #eed9a8; }
  .cmp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; }
  .cmp-item { border: 1px solid var(--border); border-radius: 10px; background: #fbfaff;
              padding: 10px 12px; font-size: 13px; line-height: 1.8; }
  .cmp-item .k { color: var(--primary-darker); font-weight: 600; display: block;
                 border-bottom: 1px dashed var(--border); margin-bottom: 6px; padding-bottom: 4px; }
  .cmp-item .k.input { color: var(--err); }
  .cmp-item .k.evidence { color: #1565c0; }
  .cmp-item .k.state { color: var(--ok); }
  .cmp-item .k.reason { color: var(--warn); }
  footer { margin-top: 22px; font-size: 12px; color: var(--muted); line-height: 1.7;
           border-top: 1px dashed var(--border); padding-top: 12px; }
"""


def parse_report(text):
    """解析 VIEW4_REPORT.md：一句话回答、逐组对照（标题/两存档行/四要素）。"""
    lines = text.splitlines()
    answer = ""
    readonly = next((l.strip() for l in lines if l.startswith("本视图为只读渲染")), "")
    pairs = []
    current = None
    in_answer = False
    for line in lines:
        s = line.strip()
        if s.startswith("## 一句话回答"):
            in_answer = True
            continue
        if s.startswith("## 对照"):
            in_answer = False
            current = {"title": s[3:], "runs": [], "items": {}}
            pairs.append(current)
        elif in_answer and s and not s.startswith("=") and not s.startswith("##"):
            answer += s
        elif current and s.startswith("- S") and "run_id：" in s:
            m = re.match(r"-\s*(S\d)\s*存档 run_id：(\S+)（verdict=(\S+)）", s)
            if m:
                current["runs"].append((m.group(1), m.group(2), m.group(3)))
        elif current and s.startswith(("输入变化：", "证据变化：", "状态结果：", "原因解释：")):
            key, val = s.split("：", 1)
            current["items"][key] = val
    return answer, readonly, pairs


def verdict_class(verdict):
    if verdict and "stable" in verdict:
        return "stable"
    if verdict and "attention" in verdict:
        return "attention"
    return "other"


def build_html(answer, readonly, pairs):
    esc = html_mod.escape
    html = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>GreenMate VIEW4 · 场景回放与对比</title>\n<style>%s</style>\n</head>\n<body>\n"
        '<div class="main-card">\n'
        "<h1>GreenMate VIEW4 · 场景回放与对比视图</h1>\n"
        '<h2>一句话回答</h2>\n<div class="answer-box">%s</div>\n' % (PAGE_CSS, esc(answer)))
    for pair in pairs:
        html += '<div class="cmp-card"><div class="cmp-title">%s</div>\n' % esc(pair["title"])
        html += '<div class="run-row">'
        for scene, rid, verdict in pair["runs"]:
            html += ('<div class="run-chip"><span class="scene">%s</span>'
                     '<span class="rid">run_id: %s</span>'
                     '<span class="tag %s">%s</span></div>' % (
                         esc(scene), esc(rid), verdict_class(verdict), esc(verdict)))
        html += '</div>\n<div class="cmp-grid">\n'
        for key, label_cls in (("输入变化", "input"), ("证据变化", "evidence"),
                               ("状态结果", "state"), ("原因解释", "reason")):
            val = pair["items"].get(key, "—")
            html += ('<div class="cmp-item"><span class="k %s">%s</span>%s</div>\n' % (
                label_cls, esc(key), esc(val).replace("\n", "<br>")))
        html += '</div></div>\n'
    html += '<footer>%s</footer>\n</div>\n</body>\n</html>\n' % esc(readonly)
    return html


def verify_consistency(md_text, html_text):
    """自检：md 中每组的关键内容必须出现在 html。"""
    missing = []
    for line in md_text.splitlines():
        s = line.strip()
        if not s or s.startswith("="):
            continue
        if s.startswith(("输入变化：", "证据变化：", "状态结果：", "原因解释：", "## 对照")):
            probe = s.split("：", 1)[1].strip() if s.startswith(("输入", "证据", "状态", "原因")) else s[3:]
            if len(probe) > 3 and html_mod.escape(probe) not in html_text:
                missing.append(probe[:50])
        elif s.startswith("- S") and "run_id：" in s:
            rid = re.search(r"run_id：([A-Za-z0-9_-]+)", s)
            if rid and rid.group(1) not in html_text:
                missing.append("run_id %s" % rid.group(1))
    return missing


def main():
    md_text = MD_FILE.read_text(encoding="utf-8")
    answer, readonly, pairs = parse_report(md_text)
    if not pairs:
        print("[错误] VIEW4_REPORT.md 解析失败（无对照分组）")
        return 1
    html_text = build_html(answer, readonly, pairs)
    HTML_FILE.write_text(html_text, encoding="utf-8")
    print("[已生成] %s" % HTML_FILE)
    missing = verify_consistency(md_text, html_text)
    if missing:
        print("[一致性自检] FAIL：%s" % missing[:5])
        return 1
    print("[一致性自检] PASS：页面内容与 VIEW4_REPORT.md 快照一致")
    print("[使用] 双击打开 %s（纯静态页面，无 JS/无网络请求）" % HTML_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
