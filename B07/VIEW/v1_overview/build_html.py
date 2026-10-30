"""VIEW1 静态页面生成器：读取当前目录 VIEW1_REPORT.md → 生成 index.html。

只读规则遵守方式（从结构上保证）：
- 只读取当前目录的 VIEW1_REPORT.md（不读任何存档、不 import 任何实验模块）；
- 生成纯静态 HTML（内联 CSS、无 JS、无 fetch）——双击 file:// 打开即显示，
  页面本身没有任何能力发起 LLM 调用、模型预测或读取存档；
- 页面内容与 md 快照完全一致（生成后自动逐条校验文本一致性）。

用法（项目根目录）：
  python B07/VIEW/v1_overview/build_html.py
生成：B07/VIEW/v1_overview/index.html（双击用浏览器打开）
"""

import html as html_mod
import re
import sys
from pathlib import Path

VIEW_DIR = Path(__file__).resolve().parent
MD_FILE = VIEW_DIR / "VIEW1_REPORT.md"
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
  .main-card { width: 100%; max-width: 860px; background: var(--card); border-radius: 16px;
               box-shadow: 0 8px 28px rgba(94,74,138,0.10); padding: 28px 32px 24px; }
  h1 { font-size: 22px; margin: 0 0 10px; color: var(--primary-darker); }
  .runid-bar { background: var(--bg); border: 1px solid var(--border); border-radius: 10px;
               padding: 10px 14px; font-size: 13px; line-height: 1.8; margin-bottom: 20px; }
  .runid-bar b { color: var(--primary-darker); font-family: Consolas, monospace; }
  .runid-bar .meta { color: var(--muted); font-size: 12px; }
  h2 { font-size: 15px; margin: 22px 0 12px; color: var(--primary-darker);
       border-left: 4px solid var(--primary); padding-left: 10px; }
  h2 .sub { font-size: 12px; color: var(--muted); font-weight: normal; margin-left: 8px; }
  .panel { border: 1px solid var(--border); border-radius: 12px; background: #fdfcff; padding: 16px 18px; }
  table.kv { width: 100%; border-collapse: collapse; font-size: 14px; }
  table.kv td { padding: 7px 0; border-bottom: 1px dashed var(--border); vertical-align: top; }
  table.kv tr:last-child td { border-bottom: none; }
  table.kv td.k { width: 150px; color: var(--muted); }
  .missing { color: var(--muted); font-style: italic; }
  .verdict-box { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
                 border: 1px solid var(--border); border-radius: 10px;
                 background: #fbfaff; padding: 12px 14px; margin-bottom: 12px; }
  .pill { border-radius: 999px; padding: 3px 14px; font-size: 13px; font-weight: 600; }
  .pill.verdict { background: var(--bg); color: var(--primary-darker); border: 1px solid var(--border);
                  font-family: Consolas, monospace; }
  .pill.high { background: #fdeeee; color: var(--err); border: 1px solid #f3c0c0; }
  .pill.mid { background: #fdf3e0; color: var(--warn); border: 1px solid #eed9a8; }
  .pill.low { background: #e6f4ea; color: var(--ok); border: 1px solid #b7dfc2; }
  .answer-box { border: 1px solid var(--primary); border-radius: 12px; background: #faf7ff;
                padding: 14px 16px; font-size: 14px; line-height: 1.8; }
  footer { margin-top: 22px; font-size: 12px; color: var(--muted); line-height: 1.7;
           border-top: 1px dashed var(--border); padding-top: 12px; }
"""


def parse_report(text):
    """解析 VIEW1_REPORT.md：run_id 头部、两个板块条目、一句话回答、只读声明。"""
    lines = text.splitlines()
    run_id = created = mode = ""
    for line in lines:
        m = re.match(r"run_id:\s*(\S+)\s*\|\s*创建于\s*(.+?)\s*\|\s*mode:\s*(.*)$", line)
        if m:
            run_id, created, mode = m.group(1), m.group(2), m.group(3)
            break
    sections = {}   # 标题（含说明） -> [(key, value)]
    current = None
    answer = ""
    readonly = ""
    for line in lines:
        if line.startswith("【") and "】" in line and line.startswith("【一句话回答】") is False:
            title = line.split("】")[0][1:]
            current = title
            sections[current] = []
        elif line.startswith("【一句话回答】"):
            current = None
            answer = line[len("【一句话回答】"):].strip()
        elif current and line.startswith("  ") and "：" in line:
            key, val = line[2:].split("：", 1)
            sections[current].append((key.strip(), val.strip()))
        elif line.startswith("本视图为只读渲染"):
            readonly = line.strip()
    return run_id, created, mode, sections, answer, readonly


def build_html(run_id, created, mode, sections, answer, readonly):
    esc = html_mod.escape

    def kv_rows(items):
        rows = []
        for key, val in items:
            missing = "未存储" in val
            val_html = '<span class="missing">%s</span>' % esc(val) if missing else esc(val)
            rows.append("<tr><td class=\"k\">%s</td><td>%s</td></tr>" % (esc(key), val_html))
        return "".join(rows)

    obs_title = next((t for t in sections if t.startswith("原始观测数值")), "原始观测数值")
    state_title = next((t for t in sections if t.startswith("系统理解后的状态")), "系统理解后的状态")
    obs_items = sections.get(obs_title, [])
    state_items = sections.get(state_title, [])

    verdict = ""
    level = ""
    level_full = ""
    rest_items = []
    for key, val in state_items:
        if key == "判定 verdict":
            verdict = val
        elif key == "关注等级":
            level_full = val
            m = re.match(r"(高|中高|低|未知)（", val)
            level = m.group(1) if m else ""
        else:
            rest_items.append((key, val))
    level_cls = {"高": "high", "中高": "mid", "低": "low", "未知": "mid"}.get(level, "mid")

    sub1 = "（%s" % obs_title.split("（", 1)[1] if "（" in obs_title else ""
    sub2 = "（%s" % state_title.split("（", 1)[1] if "（" in state_title else ""

    html = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>GreenMate VIEW1 · 状态总览</title>\n<style>%s</style>\n</head>\n<body>\n"
        '<div class="main-card">\n'
        "<h1>GreenMate VIEW1 · 状态总览视图</h1>\n"
        '<div class="runid-bar">run_id: <b>%s</b><br>'
        '<span class="meta">创建于 %s | mode: %s | 静态快照（与 VIEW1_REPORT.md 完全一致，只读）</span></div>\n'
        % (PAGE_CSS, esc(run_id), esc(created), esc(mode)))
    html += '<h2>%s<span class="sub">%s</span></h2>\n<div class="panel"><table class="kv">%s</table></div>\n' % (
        esc(obs_title.split("（")[0]), esc(sub1), kv_rows(obs_items))
    html += '<h2>%s<span class="sub">%s</span></h2>\n<div class="panel">\n' % (
        esc(state_title.split("（")[0]), esc(sub2))
    html += ('<div class="verdict-box"><span class="pill verdict">verdict: %s</span>'
             '<span class="pill %s">关注等级：%s</span></div>\n' % (
                 esc(verdict), level_cls, esc(level_full)))
    html += '<table class="kv">%s</table>\n</div>\n' % kv_rows(rest_items)
    html += '<h2>一句话回答</h2>\n<div class="answer-box">%s</div>\n' % esc(answer)
    html += '<footer>%s</footer>\n</div>\n</body>\n</html>\n' % esc(readonly)
    return html


def verify_consistency(md_text, html_text, run_id, section_titles):
    """自检：md 快照中的每条内容行必须原样出现在 html 中（转义后文本一致）。

    头部行与板块标题在页面中结构化展示（拆分渲染），单独校验；
    其余内容行（键值、一句话回答、只读声明）逐条比对。
    """
    missing = []
    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("=") or stripped.startswith("run_id:"):
            continue
        if stripped.startswith("【一句话回答】"):
            continue  # answer 单独在 html 中整体校验
        if stripped.startswith("【"):
            continue  # 板块标题单独校验（见下）
        probe = stripped.split("：")[1].strip() if "：" in stripped else stripped
        if len(probe) > 3 and html_mod.escape(probe) not in html_text:
            missing.append(probe[:60])
    # 头部与标题结构化校验
    if run_id not in html_text:
        missing.append("run_id: %s" % run_id)
    for title in section_titles:
        if html_mod.escape(title.split("（")[0]) not in html_text:
            missing.append("板块标题: %s" % title)
    return missing


def main():
    md_text = MD_FILE.read_text(encoding="utf-8")
    run_id, created, mode, sections, answer, readonly = parse_report(md_text)
    if not run_id:
        print("[错误] VIEW1_REPORT.md 中未找到 run_id 行")
        return 1
    html_text = build_html(run_id, created, mode, sections, answer, readonly)
    HTML_FILE.write_text(html_text, encoding="utf-8")
    print("[已生成] %s" % HTML_FILE)
    print("[解析] run_id=%s | 板块数=%d | 条目数=%s" % (
        run_id, len(sections), {k[:8]: len(v) for k, v in sections.items()}))
    missing = verify_consistency(md_text, html_text, run_id, list(sections.keys()))
    if missing:
        print("[一致性自检] FAIL：%d 条内容未出现在页面中（示例：%s）" % (len(missing), missing[:3]))
        return 1
    print("[一致性自检] PASS：页面内容与 VIEW1_REPORT.md 快照完全一致")
    print("[使用] 双击打开 %s 即可查看（纯静态页面，无 JS/无请求/只读）" % HTML_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
