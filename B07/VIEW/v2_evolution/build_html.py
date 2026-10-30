"""VIEW2 静态页面生成器：读取 VIEW2_REPORT.md → 生成 index.html（含 SVG 时序曲线）。

只读规则：只读当前目录 md 快照；生成纯静态 HTML（内联 CSS + 内嵌 SVG，
无 JS、无 fetch、无任何外部请求）；内容与 md 快照逐条一致（自动校验）。

用法（项目根目录）：
  python B07/VIEW/v2_evolution/build_html.py
生成：B07/VIEW/v2_evolution/index.html（双击浏览器打开）
"""

import html as html_mod
import re
import sys
from pathlib import Path

VIEW_DIR = Path(__file__).resolve().parent
MD_FILE = VIEW_DIR / "VIEW2_REPORT.md"
HTML_FILE = VIEW_DIR / "index.html"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE_CSS = """
  :root {
    --primary: #b39ddb; --primary-dark: #9575cd; --primary-darker: #7e57c2;
    --bg: #f3effa; --card: #ffffff; --border: #e3ddf0; --text: #332f3d; --muted: #8a8498;
    --ok: #1b7a3d; --warn: #b26a00; --err: #c62828; --s1: #42a5f5; --s2: #ef5350;
  }
  * { box-sizing: border-box; }
  body { font-family: system-ui, "Microsoft YaHei", sans-serif; background: var(--bg);
         color: var(--text); margin: 0; padding: 32px 16px; display: flex; justify-content: center; }
  .main-card { width: 100%; max-width: 900px; background: var(--card); border-radius: 16px;
               box-shadow: 0 8px 28px rgba(94,74,138,0.10); padding: 28px 32px 24px; }
  h1 { font-size: 22px; margin: 0 0 10px; color: var(--primary-darker); }
  .runid-bar { background: var(--bg); border: 1px solid var(--border); border-radius: 10px;
               padding: 10px 14px; font-size: 13px; line-height: 1.8; margin-bottom: 20px; }
  .runid-bar b { color: var(--primary-darker); font-family: Consolas, monospace; }
  .runid-bar .meta { color: var(--muted); font-size: 12px; }
  h2 { font-size: 15px; margin: 22px 0 12px; color: var(--primary-darker);
       border-left: 4px solid var(--primary); padding-left: 10px; }
  h3 { font-size: 14px; margin: 14px 0 8px; color: var(--primary-darker); }
  .panel { border: 1px solid var(--border); border-radius: 12px; background: #fdfcff; padding: 16px 18px; }
  .chart-box { border: 1px solid var(--border); border-radius: 12px; background: #fbfaff;
               padding: 14px 16px; margin-bottom: 12px; }
  .legend { font-size: 12px; color: var(--muted); margin: 4px 0 8px; }
  .legend .s1 { color: var(--s1); font-weight: 600; }
  .legend .s2 { color: var(--s2); font-weight: 600; }
  .node-list { font-size: 13px; line-height: 1.8; }
  .node-list li { margin: 6px 0; }
  .node-list b { color: var(--primary-darker); }
  table.kv { width: 100%; border-collapse: collapse; font-size: 13px; }
  table.kv td { padding: 6px 0; border-bottom: 1px dashed var(--border); vertical-align: top; }
  table.kv tr:last-child td { border-bottom: none; }
  table.kv td.k { width: 130px; color: var(--muted); }
  .answer-box { border: 1px solid var(--primary); border-radius: 12px; background: #faf7ff;
                padding: 14px 16px; font-size: 14px; line-height: 1.8; }
  footer { margin-top: 22px; font-size: 12px; color: var(--muted); line-height: 1.7;
           border-top: 1px dashed var(--border); padding-top: 12px; }
"""


def parse_report(text):
    """解析 VIEW2_REPORT.md：头部、两条路径序列、状态节点、存档数据、一句话回答。"""
    lines = text.splitlines()
    run_id = created = mode = ""
    for line in lines:
        m = re.match(r"run_id:\s*(\S+)\s*\|\s*创建于\s*(.+?)\s*\|\s*mode:\s*(.*)$", line)
        if m:
            run_id, created, mode = m.group(1), m.group(2), m.group(3)
            break
    readonly = next((l.strip() for l in lines if l.startswith("本视图为只读渲染")), "")

    paths = []
    nodes = []
    archive_rows = []
    answer = ""
    current_path = None
    in_nodes = in_archive = in_answer = False
    for line in lines:
        s = line.strip()
        if s.startswith("### ") and ("S1" in s or "S2" in s):
            current_path = {"name": s[4:].strip(), "temps": [], "hums": [], "lights": [],
                            "shape": "", "evolution": ""}
            paths.append(current_path)
            in_nodes = in_archive = False
        elif s.startswith("温度序列"):
            current_path["temps"] = [float(v) for v in s.split(":", 1)[1].split(",")]
        elif s.startswith("湿度序列"):
            current_path["hums"] = [float(v) for v in s.split(":", 1)[1].split(",")]
        elif s.startswith("光照序列"):
            current_path["lights"] = [float(v) for v in s.split(":", 1)[1].split(",")]
        elif s.startswith("形态：") and current_path:
            current_path["shape"] = s[3:]
        elif s.startswith("演化解释：") and current_path:
            current_path["evolution"] = s[5:]
        elif s.startswith("## 状态节点"):
            in_nodes, in_archive, in_answer, current_path = True, False, False, None
        elif s.startswith("## 本存档演化数据"):
            in_nodes, in_archive, in_answer, current_path = False, True, False, None
        elif s.startswith("## 一句话回答"):
            in_nodes, in_archive, in_answer, current_path = False, False, True, None
        elif in_nodes and s.startswith("- **"):
            m = re.match(r"-\s*\*\*(.+?)\*\*（(.+?)）：(.+)", s)
            if m:
                nodes.append((m.group(1), m.group(2), m.group(3)))
        elif in_archive and "：" in s and not s.startswith("##"):
            key, val = s.split("：", 1)
            archive_rows.append((key.strip(), val.strip()))
        elif in_answer and s and not s.startswith("##"):
            answer += s
    return run_id, created, mode, readonly, paths, nodes, archive_rows, answer


def svg_line(values, y_min, y_max, color, label, mark_end=True, mark_mid=False):
    """生成一条折线 SVG 片段（纯文本嵌入 HTML，无 JS）。"""
    width, height = 520, 170
    pad_l, pad_r, pad_t, pad_b = 42, 18, 16, 26
    n = len(values)
    xs = [pad_l + i * (width - pad_l - pad_r) / (n - 1) for i in range(n)]
    ys = [pad_t + (height - pad_t - pad_b) * (1 - (v - y_min) / max(y_max - y_min, 1e-6))
          for v in values]
    pts = " ".join("%.1f,%.1f" % (x, y) for x, y in zip(xs, ys))
    parts = ['<polyline points="%s" fill="none" stroke="%s" stroke-width="2.5" '
             'stroke-linejoin="round"/>' % (pts, color)]
    for i, (x, y) in enumerate(zip(xs, ys)):
        if (i == 0 or i == n - 1 or (mark_mid and i == n - 2)):
            parts.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>' % (x, y, color))
    parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="%s">%s</text>' % (
        xs[-1] + 5, ys[-1] + 4, color, label))
    return "".join(parts)


def svg_grid(y_min, y_max, width=520, height=170, pad_l=42, pad_r=18, pad_t=16, pad_b=26):
    """坐标网格（动态步长，最多约 6 条线）+ 30℃ 阈值虚线。"""
    span = max(y_max - y_min, 1e-6)
    step = span / 5.0
    parts = []
    for i in range(6):
        v = y_min + step * i
        y = pad_t + (height - pad_t - pad_b) * (1 - (v - y_min) / span)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#eee9f6" '
                     'stroke-width="1"/>' % (pad_l, y, width - pad_r, y))
        parts.append('<text x="8" y="%.1f" font-size="10" fill="#8a8498">%s</text>'
                     % (y + 3, int(v)))
    if y_min <= 30 <= y_max:
        y = pad_t + (height - pad_t - pad_b) * (1 - (30 - y_min) / span)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#b26a00" '
                     'stroke-width="1" stroke-dasharray="5,4"/>' % (pad_l, y, width - pad_r, y))
        parts.append('<text x="%d" y="%.1f" font-size="10" fill="#b26a00">30℃ 高温边界</text>'
                     % (width - pad_r - 92, y - 4))
    return "".join(parts)


def build_html(run_id, created, mode, readonly, paths, nodes, archive_rows, answer):
    esc = html_mod.escape
    html = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>GreenMate VIEW2 · 状态演化视图</title>\n<style>%s</style>\n</head>\n<body>\n"
        '<div class="main-card">\n'
        "<h1>GreenMate VIEW2 · 状态演化视图</h1>\n"
        '<div class="runid-bar">run_id: <b>%s</b><br>'
        '<span class="meta">创建于 %s | mode: %s | 静态快照（只读，演化过程与状态标记）</span></div>\n'
        % (PAGE_CSS, esc(run_id), esc(created), esc(mode)))

    # 温度对照大图
    html += '<h2>演化路径对照（同样到达 30℃，两条路径如何形成状态）</h2>\n'
    for key, p in (("温度", "temps"), ("湿度", "hums"), ("光照", "lights")):
        s1_vals = paths[0][p]
        s2_vals = paths[1][p]
        if key == "温度":
            y_min, y_max = 20, 42
        elif key == "湿度":
            y_min, y_max = 40, 55
        else:
            y_min, y_max = 0, 13000
        html += ('<div class="chart-box" data-s1-values="%s" data-s2-values="%s">'
                 '<div class="legend">%s演化曲线：'
                 '<span class="s1">■ S1 稳态维持</span>　<span class="s2">■ S2 持续升温</span>'
                 '（7 个采样点，30 分钟/点）</div>\n<svg viewBox="0 0 560 180" '
                 'style="width:100%%;height:auto;">%s%s%s</svg></div>\n' % (
                     ",".join(str(v) for v in s1_vals),
                     ",".join(str(v) for v in s2_vals),
                     key, svg_grid(y_min, y_max),
                     svg_line(s1_vals, y_min, y_max, "#42a5f5", "S1 末点 %.1f" % s1_vals[-1]),
                     svg_line(s2_vals, y_min, y_max, "#ef5350", "S2 末点 %.1f" % s2_vals[-1],
                              mark_mid=True)))

    # 形态与演化解释
    for path in paths:
        html += ('<h3>%s</h3>\n<div class="panel">形态：%s<br>演化解释：%s</div>\n' % (
            esc(path["name"]), esc(path["shape"]), esc(path["evolution"])))

    # 状态节点时间线
    html += '<h2>状态节点（判定切换与风险变化）</h2>\n<div class="panel"><ul class="node-list">\n'
    for title, when, why in nodes:
        html += '<li><b>%s</b>（%s）：%s</li>\n' % (esc(title), esc(when), esc(why))
    html += '</ul></div>\n'

    # 存档演化数据
    html += '<h2>本存档演化数据（run_id 自带，只读提取）</h2>\n<div class="panel"><table class="kv">\n'
    for key, val in archive_rows:
        html += '<tr><td class="k">%s</td><td>%s</td></tr>\n' % (esc(key), esc(val))
    html += '</table></div>\n'

    html += '<h2>一句话回答</h2>\n<div class="answer-box">%s</div>\n' % esc(answer)
    html += '<footer>%s</footer>\n</div>\n</body>\n</html>\n' % esc(readonly)
    return html


def verify_consistency(md_text, html_text, run_id):
    """自检：md 中数值序列与关键内容必须出现在 html。

    序列行（温度/湿度/光照）在页面中以 SVG 折线呈现（数值编码为坐标），
    按逐个数值比对；其余内容行按全文比对。
    """
    missing = []
    for line in md_text.splitlines():
        s = line.strip()
        if not s or s.startswith("="):
            continue
        if s.startswith(("温度序列", "湿度序列", "光照序列")):
            nums = [v.strip() for v in s.split(":", 1)[1].split(",")]
            for num in nums:
                if num not in html_text:
                    missing.append("数值 %s" % num)
            continue
        if s.startswith("run_id:"):
            continue  # 头部行在页面中结构化展示，单独校验 run_id
        if s.startswith(("形态：", "演化解释：", "- **")) or (
                "：" in s and s.startswith(("历史窗口", "模型判定", "天气预报温度", "判定结论"))):
            probe = s.split("：", 1)[1].strip() if "：" in s else s
            if len(probe) > 3 and html_mod.escape(probe) not in html_text:
                missing.append(probe[:60])
    if run_id not in html_text:
        missing.append("run_id")
    if "S1 稳态维持" not in html_text or "S2 持续升温" not in html_text:
        missing.append("演化路径标题")
    return missing


def main():
    md_text = MD_FILE.read_text(encoding="utf-8")
    run_id, created, mode, readonly, paths, nodes, archive_rows, answer = parse_report(md_text)
    if not run_id or len(paths) != 2:
        print("[错误] VIEW2_REPORT.md 解析失败（run_id=%s, paths=%d）" % (run_id, len(paths)))
        return 1
    html_text = build_html(run_id, created, mode, readonly, paths, nodes, archive_rows, answer)
    HTML_FILE.write_text(html_text, encoding="utf-8")
    print("[已生成] %s" % HTML_FILE)
    missing = verify_consistency(md_text, html_text, run_id)
    if missing:
        print("[一致性自检] FAIL：%s" % missing[:5])
        return 1
    print("[一致性自检] PASS：页面内容与 VIEW2_REPORT.md 快照一致")
    print("[使用] 双击打开 %s（纯静态页面，内嵌 SVG，无 JS/无请求）" % HTML_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
