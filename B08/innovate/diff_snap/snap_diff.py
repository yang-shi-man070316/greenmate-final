"""模块3：历史风险轨迹差分对比（独立后置分析工具，只读）。

支持同场景跨 run 对比（B08 内部相邻 run、B07 旧 run 对比 B08 新 run 均可）。
对比维度（只输出客观差异描述，不新增预判、风险结论）：
- verdict（陈述相同/不同）
- 趋势斜率（历史序列前后半均值差，客观数值 + 差值）
- 可信度（复用模块1打分，两值 + 差值）
- 证据状态变化（各证据 status 对照：ok/unavailable/absent）

无历史快照时输出提示文本。

用法（项目根目录）：
  python B08/innovate/diff_snap/snap_diff.py --file-a <旧json> --file-b <新json>
  python B08/innovate/diff_snap/snap_diff.py --dir <目录>    # 自动取同场景最新两条
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
for d in (ROOT / "B08", ROOT / "B08" / "innovate" / "score",
          ROOT / "B07" / "S5", ROOT / "B07" / "S4", ROOT / "B07" / "S3",
          ROOT / "B07" / "S2", ROOT / "B07" / "S1", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from evidence_score import score_record  # noqa: E402 （复用模块1，只读）

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def judgment_of(record):
    return (record.get("structured_judgment")
            or record.get("step4_structured_judgment")
            or record.get("judgment") or {})


def slope_of(record):
    """历史序列前后半均值差（客观统计）。"""
    samples = (record.get("history_series") or record.get("history_window")
               or (record.get("step2_recent_history_3h") or {}).get("data", {}).get("samples"))
    if not samples:
        temps = []
        ev = next((e for e in record.get("adopted_evidence", []) + record.get("evidence", [])
                   if e.get("source_type") == "internal_history"), None)
        r = (ev or {}).get("result") or {}
        if r.get("temperature_first") is not None:
            temps = [r["temperature_first"], r["temperature_last"]]
    else:
        temps = [p["temperature"] for p in samples]
    if len(temps) < 2:
        return None
    half = len(temps) // 2
    first, second = temps[:half], temps[half:]
    return round((sum(second) / len(second)) - (sum(first) / len(first)), 2)


def evidence_states(record):
    """各证据状态（只读提取，兼容 B07 各记录与 B08 v8 记录结构）。"""
    states = {}
    for ev in record.get("adopted_evidence", []) + record.get("evidence", []):
        states[ev.get("source_type")] = ev.get("status")
    for ev in record.get("missing_evidence", []):
        states[ev.get("source_type")] = ev.get("status")
    if (record.get("weather_forecast") or {}).get("status") and "external_weather" not in states:
        states["external_weather"] = record["weather_forecast"]["status"]
    if (record.get("weather_evidence") or {}).get("status") and "external_weather" not in states:
        states["external_weather"] = record["weather_evidence"]["status"]
    if (record.get("history_window") or record.get("history_series")
            or record.get("history_samples")):
        states.setdefault("internal_history", "ok")
    if record.get("step2_recent_history_3h"):
        states.setdefault("internal_history",
                          record["step2_recent_history_3h"].get("status", "ok"))
    return states


def diff(record_a, record_b):
    """只输出客观差异描述。"""
    ja, jb = judgment_of(record_a), judgment_of(record_b)
    sa, sb = slope_of(record_a), slope_of(record_b)
    ca, cb = score_record(record_a), score_record(record_b)
    ea, eb = evidence_states(record_a), evidence_states(record_b)

    lines = [
        "=" * 64,
        "历史风险轨迹差分对比（客观差异描述，不含新增预判）",
        "=" * 64,
        "A（旧）：%s（%s）" % (record_a.get("run_id", "?"),
                               record_a.get("created_at") or record_a.get("analysis_time", "?")),
        "B（新）：%s（%s）" % (record_b.get("run_id", "?"),
                               record_b.get("created_at") or record_b.get("analysis_time", "?")),
        "",
        "## verdict",
        "- A：%s；B：%s —— %s" % (ja.get("verdict"), jb.get("verdict"),
                                  "相同" if ja.get("verdict") == jb.get("verdict") else "不同"),
        "",
        "## 趋势斜率（历史序列前后半均值差）",
    ]
    if sa is None or sb is None:
        lines.append("- 无历史快照：%s（提示：缺少可对比的历史序列，不做趋势差分）" % (
            "A 或 B 缺少历史序列"))
    else:
        lines.append("- A：%+.2f℃；B：%+.2f℃；差值（B−A）：%+.2f℃（仅为客观数值变化）"
                     % (sa, sb, round(sb - sa, 2)))
    lines += [
        "",
        "## 证据可信度（模块1打分）",
        "- A：%.2f（%s）；B：%.2f（%s）；差值：%+.2f" % (
            ca["confidence_total"], ca["confidence_note"],
            cb["confidence_total"], cb["confidence_note"],
            round(cb["confidence_total"] - ca["confidence_total"], 2)),
        "",
        "## 证据状态变化",
    ]
    all_types = sorted(set(ea) | set(eb))
    if not all_types:
        lines.append("- 两记录均无证据状态信息（无历史快照，不做证据差分）")
    for st in all_types:
        a, b = ea.get(st, "absent"), eb.get(st, "absent")
        mark = "（无变化）" if a == b else "（有变化：%s → %s）" % (a, b)
        lines.append("- %s：A=%s，B=%s %s" % (st, a, b, mark))
    lines += [
        "",
        "> 本输出仅为客观差异描述：逐字段陈述相同/不同与数值变化，"
        "不新增风险结论、不做预判。",
    ]
    return "\n".join(lines)


def find_latest_two(paths):
    """同场景（同名文件前缀）最新两条。"""
    by_name = {}
    for p in paths:
        base = p.stem.split("-")[0] if "-" in p.stem else p.stem
        by_name.setdefault(base, []).append(p)
    for base, ps in by_name.items():
        ps.sort()
        if len(ps) >= 2:
            yield ps[-2], ps[-1]


def main():
    parser = argparse.ArgumentParser(description="历史风险轨迹差分对比（只读）")
    parser.add_argument("--file-a", help="旧 run json")
    parser.add_argument("--file-b", help="新 run json")
    parser.add_argument("--dir", help="目录：自动取同场景最新两条对比")
    args = parser.parse_args()

    if args.file_a and args.file_b:
        a = json.loads(Path(args.file_a).read_text(encoding="utf-8"))
        b = json.loads(Path(args.file_b).read_text(encoding="utf-8"))
        print(diff(a, b))
        return 0
    if args.dir:
        paths = sorted(Path(args.dir).glob("*.json"))
        pairs = list(find_latest_two(paths))
        if not pairs:
            print("目录中未找到可对比的相邻记录（无历史快照，不做差分）")
            return 0
        for a_path, b_path in pairs:
            a = json.loads(a_path.read_text(encoding="utf-8"))
            b = json.loads(b_path.read_text(encoding="utf-8"))
            print(diff(a, b))
            print()
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
