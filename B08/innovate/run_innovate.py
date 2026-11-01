"""B08 创新模块串行入口：打分 → 溯源视图 → 快照差分。

接入规则：
- B08 新 run：运行结束追加 _innovate 字段到 json 存档（新增键，原有字段保留不变），
  并生成溯源视图（md + html）与差分报告到 B08/innovate/output/；
- B01~B07 历史存档：只读分析（不写回原文件），产出到 output/。

用法（项目根目录）：
  python B08/innovate/run_innovate.py --file <json>            # 单条：打分+溯源+差分
  python B08/innovate/run_innovate.py --b08                     # B08 verify 5 条 + 回归 10 例
  python B08/innovate/run_innovate.py --b07-dir <目录>          # B07 存档批量只读分析
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B08", ROOT / "B08" / "innovate" / "score",
          ROOT / "B08" / "innovate" / "trace_view",
          ROOT / "B08" / "innovate" / "diff_snap",
          ROOT / "B07" / "S5", ROOT / "B07" / "S4", ROOT / "B07" / "S3",
          ROOT / "B07" / "S2", ROOT / "B07" / "S1", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from diff_snap.snap_diff import diff  # noqa: E402
from evidence_score import score_record  # noqa: E402
from trace_view.render_trace import build_trace, render_html, render_markdown  # noqa: E402

INNOVATE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = INNOVATE_DIR / "output"

V8_RECORDS = [
    "B08/verify/v8-20261031072937-a6b34e.json",
    "B08/verify/v8-20261031072941-cbce4e.json",
    "B08/verify/v8-20261031072945-389510.json",
    "B08/verify/v8-20261031072949-fee711.json",
    "B08/verify/v8-20261031072952-75625a.json",
]

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def process_record(path, write_back):
    """串行：打分 → 溯源视图 → 差分。write_back=True 时向 json 追加 _innovate 字段。"""
    record = json.loads(path.read_text(encoding="utf-8"))
    # 1. 打分
    score = score_record(record)
    # 2. 溯源视图
    trace = build_trace(record)
    md = render_markdown(trace)
    html = render_html(trace)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    (OUTPUT_DIR / ("%s_score.md" % stem)).write_text(
        "# 证据可信度打分：%s\n\n- 综合可信度：**%.2f**（%s）\n- 单项：%s\n- 权重：%s\n- 完整性扣分：%s\n"
        % (path.name, score["confidence_total"], score["confidence_note"],
           json.dumps(score["evidence_score"], ensure_ascii=False),
           json.dumps(score["weights"]), score["integrity_penalty"]), encoding="utf-8")
    (OUTPUT_DIR / ("%s_trace.md" % stem)).write_text(md, encoding="utf-8")
    (OUTPUT_DIR / ("%s_trace.html" % stem)).write_text(html, encoding="utf-8")
    # 3. 差分：与同场景前一条相邻记录对比
    diff_text = _diff_with_previous(path)
    if diff_text:
        (OUTPUT_DIR / ("%s_diff.md" % stem)).write_text(diff_text, encoding="utf-8")
    # 4. 追加字段（仅 B08 新 run；只更新 _innovate 键，原有字段保留不变）
    if write_back:
        record["_innovate"] = {
            "evidence_score": score["evidence_score"],
            "confidence_total": score["confidence_total"],
            "confidence_note": score["confidence_note"],
            "trace_generated": True,
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print("%s：打分 %.2f（%s），_innovate 已追加，视图与差分已生成" % (
            path.name, score["confidence_total"], score["confidence_note"]))
    else:
        print("%s：打分 %.2f（%s），视图已生成（只读，不回写）" % (
            path.name, score["confidence_total"], score["confidence_note"]))
    return score, trace


def _diff_with_previous(path):
    """与同目录相邻一条同前缀记录做差分；无历史快照则返回提示文本。"""
    siblings = sorted(path.parent.glob("*.json"))
    idx = [p.name for p in siblings].index(path.name)
    if idx == 0:
        return "# 差分：%s\n\n无历史快照（该目录中无更早的相邻记录），不做差分。\n" % path.name
    prev = siblings[idx - 1]
    try:
        a = json.loads(prev.read_text(encoding="utf-8"))
        b = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return diff(a, b)


def main():
    parser = argparse.ArgumentParser(description="创新模块串行入口")
    parser.add_argument("--file", help="单条 json 存档")
    parser.add_argument("--b08", action="store_true", help="处理 B08 verify 5 条 + 回归 10 例")
    parser.add_argument("--b07-dir", help="B07 存档目录批量只读分析")
    args = parser.parse_args()

    if args.file:
        process_record(Path(args.file), write_back=False)
        return 0
    if args.b08:
        for rel in V8_RECORDS:
            process_record(ROOT / rel, write_back=True)
        # 回归 10 例：处理 cases/ 中的固定快照（runs/ 是执行结果记录，非证据存档）
        cases_dir = ROOT / "B08" / "regression" / "cases"
        for path in sorted(cases_dir.glob("case_*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            snapshot = case.get("snapshot") or {}
            score = score_record(snapshot)
            trace = build_trace(snapshot)
            stem = path.stem
            (OUTPUT_DIR / ("%s_score.md" % stem)).write_text(
                "# 证据可信度打分（回归案例快照）：%s\n\n- 综合可信度：**%.2f**（%s）\n- 单项：%s\n"
                % (path.name, score["confidence_total"], score["confidence_note"],
                   json.dumps(score["evidence_score"], ensure_ascii=False)),
                encoding="utf-8")
            (OUTPUT_DIR / ("%s_trace.md" % stem)).write_text(render_markdown(trace),
                                                              encoding="utf-8")
            (OUTPUT_DIR / ("%s_trace.html" % stem)).write_text(render_html(trace),
                                                                encoding="utf-8")
            print("%s（回归快照）：打分 %.2f（%s）" % (
                path.name, score["confidence_total"], score["confidence_note"]))
        return 0
    if args.b07_dir:
        for path in sorted(Path(args.b07_dir).glob("*.json")):
            try:
                process_record(path, write_back=False)
            except Exception as e:
                print("%s：跳过（%s）" % (path.name, e))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
