"""VIEW3 静态页面生成器：读取 VIEW3_REPORT.md → 生成 index.html（证据空间卡片）。

只读规则：只读当前目录 md 快照；纯静态 HTML（内联 CSS，无 JS、无网络请求）；
内容与 md 快照逐条一致（自动校验）。

用法（项目根目录）：
  python B07/VIEW/v3_evidence/build_html.py
生成：B07/VIEW/v3_evidence/index.html（双击浏览器打开）
"""

import html as html_mod
import re
import sys
from pathlib import Path

VIEW_DIR = Path(__file__).resolve().parent
MD_FILE = VIEW_DIR / "VIEW3_REPORT.md"
HTML_FILE = VIEW_DIR / "index.html"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE_CSS = """
  :root {
    --primary: #b39ddb; --primary-dark: #9575cd; --primary-darker: #7e57c2;
    --bg: #f3effa; --card: #ffffff; --border: #e3ddf0; --text: #332f3d; --muted: #8a8498;
    --ok: #1b7a3d; --warn: #b26a00; --err: #c62828; --blue: #1565c0;
  }
  * { box-sizing: border-box; }
  body { font-family: system-ui, "Microsoft YaHei", sans-serif; background: var(--bg);
         color: var(--text); margin: 0; padding: 32px 16px; display: flex; justify-content: center; }
  .main-card { width: 100%; max-width: 920px; background: var(--card); border-radius: 16px;
               box-shadow: 0 8px 28px rgba(94,74,138,0.10); padding: 28px 32px 24px; }
  h1 { font-size: 22px; margin: 0 0 10px; color: var(--primary-darker); }
  .runid-bar { background: var(--bg); border: 1px solid var(--border); border-radius: 10px;
               padding: 10px 14px; font-size: 13px; line-height: 1.8; margin-bottom: 20px; }
  .runid-bar b { color: var(--primary-darker); font-family: Consolas, monospace; }
  .runid-bar .meta { color: var(--muted); font-size: 12px; }
  h2 { font-size: 15px; margin: 24px 0 12px; color: var(--primary-darker);
       border-left: 4px solid var(--primary); padding-left: 10px; }
  h3 { font-size: 14px; margin: 14px 0 8px; color: var(--primary-darker); }
  .ev-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
  .ev-card { border: 1px solid var(--border); border-radius: 12px; background: #fdfcff;
             padding: 14px 16px; }
  .ev-card .head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  .ev-card .name { font-weight: 600; font-size: 14px; color: var(--primary-darker); }
  .tag { border-radius: 999px; padding: 1px 10px; font-size: 11px; font-weight: 600; }
  .tag.ok { background: #e6f4ea; color: var(--ok); border: 1px solid #b7dfc2; }
  .tag.warn { background: #fdf3e0; color: var(--warn); border: 1px solid #eed9a8; }
  .tag.err { background: #fdeeee; color: var(--err); border: 1px solid #f3c0c0; }
  .ev-card .q { font-size: 13px; line-height: 1.8; }
  .ev-card .q .k { color: var(--muted); margin-right: 4px; }
  .tools-panel { border: 1px solid var(--border); border-radius: 12px; background: #fdfcff;
                 padding: 14px 16px; font-size: 12px; line-height: 1.9; }
  .dir-list { font-size: 13px; line-height: 2; }
  .dir-support { color: var(--err); font-weight: 600; }
  .dir-reverse { color: var(--blue); font-weight: 600; }
  .dir-limit { color: var(--warn); font-weight: 600; }
  .missing-box { border: 1px solid #eed9a8; border-radius: 12px; background: #fdf6e8;
                 padding: 14px 16px; font-size: 13px; line-height: 1.9; }
  .answer-box { border: 1px solid var(--primary); border-radius: 12px; background: #faf7ff;
                padding: 14px 16px; font-size: 14px; line-height: 1.8; }
  footer { margin-top: 22px; font-size: 12px; color: var(--muted); line-height: 1.7;
           border-top: 1px dashed var(--border); padding-top: 12px; }
"""


def parse_report(text):
    """解析 VIEW3_REPORT.md：头部、四类证据三问、工具状态、分歧案例、缺失案例、一句话回答。"""
    lines = text.splitlines()
    run_id = created = mode = ""
    for line in lines:
        m = re.match(r"run_id:\s*(\S+)\s*\|\s*创建于\s*(.+?)\s*\|\s*mode:\s*(.*)$", line)
        if m:
            run_id, created, mode = m.group(1), m.group(2), m.group(3)
            break
    readonly = next((l.strip() for l in lines if l.startswith("本视图为只读渲染")), "")
    verdict = next((l.strip() for l in lines if l.startswith("判定：")), "")

    evidence = {}   # name -> {source, content, validity}
    tools = []
    s4_lines = []
    s5_lines = []
    answer = ""
    current_ev = None
    in_tools = in_s4 = in_s5 = in_answer = False
    for line in lines:
        s = line.strip()
        if s.startswith("### ") and not s.startswith("### 工具"):
            current_ev = s[4:].strip()
            evidence[current_ev] = {}
            in_tools = in_s4 = in_s5 = in_answer = False
        elif s.startswith("### 工具与运行状态"):
            current_ev = None
            in_tools, in_s4, in_s5, in_answer = True, False, False, False
        elif s.startswith("## 证据分歧案例"):
            current_ev = None
            in_tools, in_s4, in_s5, in_answer = False, True, False, False
        elif s.startswith("## 证据缺失案例"):
            current_ev = None
            in_tools, in_s4, in_s5, in_answer = False, False, True, False
        elif s.startswith("## 一句话回答"):
            current_ev = None
            in_tools, in_s4, in_s5, in_answer = False, False, False, True
        elif current_ev and s.startswith("来源："):
            evidence[current_ev]["source"] = s[3:]
        elif current_ev and s.startswith("内容："):
            evidence[current_ev]["content"] = s[3:]
        elif current_ev and s.startswith("有效性："):
            evidence[current_ev]["validity"] = s[4:]
        elif in_tools and s.startswith("- "):
            tools.append(s[2:])
        elif in_tools and s.startswith("链状态："):
            tools.append("链状态：" + s[4:])
        elif in_s4 and s.startswith("- "):
            s4_lines.append(s[2:])
        elif in_s5 and s.startswith("- "):
            s5_lines.append(s[2:])
        elif in_answer and s and not s.startswith("##"):
            answer += s
    return run_id, created, mode, readonly, verdict, evidence, tools, s4_lines, s5_lines, answer


def validity_tag(validity):
    if "有效（ok）" in validity and "无匹配" not in validity:
        return "ok"
    if "不可用" in validity or "无匹配" in validity:
        return "warn"
    return "err"


def build_html(run_id, created, mode, readonly, verdict, evidence, tools,
               s4_lines, s5_lines, answer):
    esc = html_mod.escape
    html = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>GreenMate VIEW3 · 证据空间视图</title>\n<style>%s</style>\n</head>\n<body>\n"
        '<div class="main-card">\n'
        "<h1>GreenMate VIEW3 · 证据空间视图</h1>\n"
        '<div class="runid-bar">run_id: <b>%s</b><br>'
        '<span class="meta">创建于 %s | mode: %s | 静态快照（只读，多源证据组织）</span></div>\n'
        % (PAGE_CSS, esc(run_id), esc(created), esc(mode)))

    html += '<h2>证据空间总览</h2>\n<div class="panel">%s</div>\n' % esc(verdict)
    html += '<h2>五类证据（每条回答三问）</h2>\n<div class="ev-grid">\n'
    for name, ev in evidence.items():
        if not ev:
            html += ('<div class="ev-card"><div class="head"><span class="name">%s</span></div>'
                     '<div class="q">（本存档未包含该类证据，如实标注）</div></div>\n' % esc(name))
            continue
        tag = validity_tag(ev.get("validity", ""))
        html += (
            '<div class="ev-card"><div class="head"><span class="name">%s</span>'
            '<span class="tag %s">%s</span></div>'
            '<div class="q"><span class="k">它从哪里来：</span>%s</div>'
            '<div class="q"><span class="k">它说了什么：</span>%s</div>'
            '<div class="q"><span class="k">它现在是否有效：</span>%s</div></div>\n' % (
                esc(name), tag, esc(ev.get("validity", "").split("（")[0]),
                esc(ev.get("source", "—")), esc(ev.get("content", "—")),
                esc(ev.get("validity", "—"))))
    html += '</div>\n'

    html += '<h2>工具与运行状态</h2>\n<div class="tools-panel">'
    html += "<br>".join(esc(t) for t in tools)
    html += '</div>\n'

    # 分歧案例：方向高亮
    html += '<h2>证据分歧案例（S4 存档，方向分类引用存档 synthesis）</h2>\n<div class="panel dir-list">\n'
    for line in s4_lines:
        colored = line
        if line.startswith("支持提高关注"):
            colored = '<span class="dir-support">%s</span>' % esc(line)
        elif line.startswith("意见相反"):
            colored = '<span class="dir-reverse">%s</span>' % esc(line)
        elif line.startswith("仅支持部分判断"):
            colored = '<span class="dir-limit">%s</span>' % esc(line)
        else:
            colored = esc(line)
        html += "%s<br>\n" % colored
    html += '</div>\n'

    html += '<h2>证据缺失案例（S5 存档，天气 unavailable）</h2>\n<div class="missing-box">\n'
    for line in s5_lines:
        if line.startswith("缺失证据"):
            html += "<b>%s</b><br>\n" % esc(line)
        else:
            html += "%s<br>\n" % esc(line)
    html += '</div>\n'

    html += '<h2>一句话回答</h2>\n<div class="answer-box">%s</div>\n' % esc(answer)
    html += '<footer>%s</footer>\n</div>\n</body>\n</html>\n' % esc(readonly)
    return html


def verify_consistency(md_text, html_text, run_id):
    """自检：md 中三问内容与关键行必须出现在 html。"""
    missing = []
    for line in md_text.splitlines():
        s = line.strip()
        if not s or s.startswith("="):
            continue
        if s.startswith(("来源：", "内容：", "有效性：")):
            probe = s.split("：", 1)[1].strip()
        elif s.startswith("- "):
            probe = s[2:]  # 页面渲染时剥离 "- " 前缀
        elif s.startswith("判定："):
            probe = s.split("：", 1)[1].strip()
        else:
            continue
        if len(probe) > 3 and html_mod.escape(probe) not in html_text:
            missing.append(probe[:50])
    if run_id not in html_text:
        missing.append("run_id")
    return missing


def main():
    md_text = MD_FILE.read_text(encoding="utf-8")
    parsed = parse_report(md_text)
    run_id, created, mode, readonly, verdict, evidence, tools, s4_lines, s5_lines, answer = parsed
    if not run_id or len(evidence) < 4:
        print("[错误] VIEW3_REPORT.md 解析失败（run_id=%s, evidence=%d）" % (run_id, len(evidence)))
        return 1
    html_text = build_html(run_id, created, mode, readonly, verdict, evidence, tools,
                           s4_lines, s5_lines, answer)
    HTML_FILE.write_text(html_text, encoding="utf-8")
    print("[已生成] %s" % HTML_FILE)
    missing = verify_consistency(md_text, html_text, run_id)
    if missing:
        print("[一致性自检] FAIL：%s" % missing[:5])
        return 1
    print("[一致性自检] PASS：页面内容与 VIEW3_REPORT.md 快照一致")
    print("[使用] 双击打开 %s（纯静态页面，无 JS/无网络请求）" % HTML_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
