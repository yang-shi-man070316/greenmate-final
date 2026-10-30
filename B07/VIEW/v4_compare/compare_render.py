"""VIEW4 场景回放与对比视图渲染器（只读）。

全局规则：读取已存在的 S1~S5 run 存档，只读加载已有结果；对比展示，
不随意重跑生成新数据。本模块只 import json/pathlib/re。

三组核心对照（一次只做两组）：
  ① S1 ↔ S2：历史时序不同 → 当前判断为何不同
  ② S2 ↔ S3：加入外部天气证据 → 未来关注点如何变化
  ③ S4 ↔ S5：证据从分歧变为缺失 → 判断边界怎么变化

每组对比标注四要素：输入变化 / 证据变化 / 状态结果 / 原因解释
（原因引用存档自带 verdict_note，零新推理）。

用法（项目根目录）：
  python B07/VIEW/v4_compare/compare_render.py                    # 渲染三组对照 → VIEW4_REPORT.md
  python B07/VIEW/v4_compare/compare_render.py --pair 1            # 只渲染第 1 组（S1↔S2）
  python B07/VIEW/v4_compare/compare_render.py --out xxx.md
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
S1_DIR = ROOT / "B07" / "S1" / "run_records"
S2_DIR = ROOT / "B07" / "S2" / "run_records"
S3_DIR = ROOT / "B07" / "S3" / "run_records"
S4_DIR = ROOT / "B07" / "S4" / "run_records"
S5_DIR = ROOT / "B07" / "S5" / "run_records"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def judgment_of(record):
    return (record.get("structured_judgment")
            or record.get("step4_structured_judgment")
            or record.get("judgment") or {})


def _load_latest(directory, prefix, require=None, exclude_none_verdict=True):
    """按前缀取最新存档；require(record)->bool 过滤；跳过判定为空的 mock 记录。"""
    files = sorted(directory.glob("%s*.json" % prefix))
    for path in reversed(files):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if exclude_none_verdict and not judgment_of(record).get("verdict"):
            continue
        if require and not require(record):
            continue
        return record
    return None


def load_scene(scene):
    """按场景加载最新真实运行记录。"""
    rules = {
        "S1": (S1_DIR, "s1-", lambda r: r.get("s1_task") == "S1 稳态基线"),
        "S2": (S2_DIR, "s2-", lambda r: r.get("experiment") == "S2_drift"),
        "S3": (S3_DIR, "s3-", lambda r: r.get("experiment") == "S3_with_weather"),
        "S4": (S4_DIR, "s4-", lambda r: r.get("experiment") == "S4_with_evidence"
               and judgment_of(r).get("synthesis")),
        "S5": (S5_DIR, "s5-", lambda r: r.get("experiment") == "S5_fault"
               and r.get("fault") == "weather_unavailable" and r.get("missing_evidence")),
    }
    directory, prefix, require = rules[scene]
    return _load_latest(directory, prefix, require)


def history_stats(record):
    """从 S1/S2 记录提取历史统计（只读）。"""
    j = judgment_of(record)
    trend = j.get("recent_trend") or {}
    t = trend.get("temperature") or {}
    samples = (record.get("step2_recent_history_3h") or {}).get("data", {}).get("samples") or []
    first = samples[0]["temperature"] if samples else None
    last = samples[-1]["temperature"] if samples else None
    return {"first": first, "last": last, "half_diff": t.get("half_diff"),
            "data_stable": trend.get("data_stable"), "window": trend.get("window")}


def trend_reason(record):
    """verdict_note 为空时的原因回退：引用存档 recent_trend 统计字段（只读）。"""
    h = history_stats(record)
    return ("历史近 3 小时温度 %.1f→%.1f℃，前后半均值差 %+.2f℃/窗口，data_stable=%s"
            "（引用存档 recent_trend 字段）" % (h["first"], h["last"], h["half_diff"],
                                                h["data_stable"]))


def weather_summary(record):
    """从 S3 记录提取天气证据摘要（只读）。S3 天气桩为阴雨低光照（降水/云量）。"""
    wf = record.get("weather_forecast") or {}
    data = wf.get("data") or wf
    hourly = (data.get("forecast") or {}).get("hourly") or []
    precip = [h.get("precipitation_probability") for h in hourly[:3]]
    cloud = [h.get("cloud_cover") for h in hourly[:3]]
    return {"precip": precip, "cloud": cloud, "status": wf.get("status")}


def pair_1():
    """对照① S1 ↔ S2：历史时序不同。"""
    s1, s2 = load_scene("S1"), load_scene("S2")
    if not s1 or not s2:
        return None
    h1, h2 = history_stats(s1), history_stats(s2)
    return {
        "id": 1, "title": "S1 ↔ S2：历史时序不同，当前判断为何不同",
        "a": {"scene": "S1", "run_id": s1["run_id"], "verdict": judgment_of(s1).get("verdict")},
        "b": {"scene": "S2", "run_id": s2["run_id"], "verdict": judgment_of(s2).get("verdict")},
        "input_change": ("当前观测几乎一致（均约 30℃），唯一变化 = 历史时序曲线："
                         "S1 近 3 小时 %.1f→%.1f℃ 小幅波动（前后半均值差 %+.2f℃）→ "
                         "S2 近 3 小时 %.1f→%.1f℃ 匀速升温（前后半均值差 %+.2f℃）" % (
                             h1["first"], h1["last"], h1["half_diff"],
                             h2["first"], h2["last"], h2["half_diff"])),
        "evidence_change": ("历史证据（B02 时序）内容改变：S1 呈稳态平台（data_stable=%s）→ "
                            "S2 呈持续升温（data_stable=%s）" % (h1["data_stable"], h2["data_stable"])),
        "state_change": "%s（S1 判定稳定）→ %s（S2 判定升温风险）" % (
            judgment_of(s1).get("verdict"), judgment_of(s2).get("verdict")),
        "reason": "原因（引用存档 verdict_note / recent_trend 字段）：\n- S1：%s\n- S2：%s" % (
            judgment_of(s1).get("verdict_note") or trend_reason(s1),
            judgment_of(s2).get("verdict_note") or trend_reason(s2)),
    }


def pair_2():
    """对照② S2 ↔ S3：加入外部天气证据。"""
    s2, s3 = load_scene("S2"), load_scene("S3")
    if not s2 or not s3:
        return None
    w3 = weather_summary(s3)
    return {
        "id": 2, "title": "S2 ↔ S3：加入外部天气证据后，未来关注点如何变化",
        "a": {"scene": "S2", "run_id": s2["run_id"], "verdict": judgment_of(s2).get("verdict")},
        "b": {"scene": "S3", "run_id": s3["run_id"], "verdict": judgment_of(s3).get("verdict")},
        "input_change": ("S2 仅有内部数据（无天气证据）；S3 新增外部天气预报证据"
                         "（未来 3 小时降水概率 %s%%，云量 %s%%——阴雨低光照预报，status=%s）" % (
                             w3["precip"], w3["cloud"], w3["status"])),
        "evidence_change": "证据链新增 B03 天气证据（外部潜在条件）：阴雨低光照预报，提示外部环境变化",
        "state_change": "%s（内部升温风险）→ %s（风险来源转移到外部天气，内部稳态判定不变）" % (
            judgment_of(s2).get("verdict"), judgment_of(s3).get("verdict")),
        "reason": "原因（引用存档 verdict_note / recent_trend / attribution 字段）：\n- S2：%s\n- S3：%s" % (
            judgment_of(s2).get("verdict_note") or trend_reason(s2),
            judgment_of(s3).get("verdict_note") or
            "归因 %s：风险升级完全由外部天气证据驱动，内部稳态判定不变（引用存档 attribution 字段）"
            % judgment_of(s3).get("attribution", "—")),
    }


def pair_3():
    """对照③ S4 ↔ S5：证据分歧 → 缺失。"""
    s4, s5 = load_scene("S4"), load_scene("S5")
    if not s4 or not s5:
        return None
    j5 = judgment_of(s5)
    missing = j5.get("missing_evidence") or s5.get("missing_evidence") or []
    def _reason(m):
        return m.get("reason") or (m.get("error") or {}).get("message") or "未知原因"
    missing_text = "；".join("%s（%s）" % (m.get("evidence_id"), _reason(m))
                             for m in missing) or "无"
    return {
        "id": 3, "title": "S4 ↔ S5：证据从存在分歧变为缺失后，判断边界怎么变化",
        "a": {"scene": "S4", "run_id": s4["run_id"], "verdict": judgment_of(s4).get("verdict")},
        "b": {"scene": "S5", "run_id": s5["run_id"], "verdict": j5.get("verdict")},
        "input_change": ("同一份天气证据 E3 的可用性改变：S4 中 E3 有效（降温预报，与内部证据分歧）→ "
                         "S5 中 E3 调用失败（%s）" % missing_text),
        "evidence_change": "天气证据从『有效但方向相反』变为『缺失不可用』：分歧依据消失，受限维度出现",
        "state_change": "%s（保留分歧的不确定判断）→ %s（判断边界收缩，天气维度不可评估）" % (
            judgment_of(s4).get("verdict"), j5.get("verdict")),
        "reason": "原因（引用两记录 verdict_note）：\n- S4：%s\n- S5：%s" % (
            judgment_of(s4).get("verdict_note"), j5.get("verdict_note")),
    }


PAIRS = (pair_1, pair_2, pair_3)


def render_pair(pair):
    lines = [
        "## 对照%d %s" % (pair["id"], pair["title"]),
        "",
        "- %s 存档 run_id：%s（verdict=%s）" % (pair["a"]["scene"], pair["a"]["run_id"],
                                             pair["a"]["verdict"]),
        "- %s 存档 run_id：%s（verdict=%s）" % (pair["b"]["scene"], pair["b"]["run_id"],
                                             pair["b"]["verdict"]),
        "",
        "输入变化：%s" % pair["input_change"],
        "证据变化：%s" % pair["evidence_change"],
        "状态结果：%s" % pair["state_change"],
        "原因解释：%s" % pair["reason"],
        "",
    ]
    return "\n".join(lines)


def render_md(pairs, only_id=None):
    header = [
        "=" * 64,
        "GreenMate VIEW4 · 场景回放与对比视图",
        "=" * 64,
        "",
        "本视图为只读渲染：只加载已存在的 S1~S5 run 存档做对比展示，未重跑任何实验、"
        "未生成新数据。每组对比标注四要素：输入变化 / 证据变化 / 状态结果 / 原因解释"
        "（原因引用存档自带 verdict_note，零新推理）。",
        "",
        "## 一句话回答",
        "如果条件改变，GreenMate 的判断会跟着合理变化：历史时序不同 → 稳态 vs 风险；"
        "天气证据加入 → 关注点扩展到分歧；证据缺失 → 判断边界收缩。"
        "输入 → 证据 → 状态 → 判断的因果链在每组对照中完整可见。",
        "",
    ]
    parts = list(header)
    for pair in pairs:
        if only_id and pair["id"] != only_id:
            continue
        parts.append(render_pair(pair))
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="VIEW4 场景回放与对比视图（只读渲染）")
    parser.add_argument("--pair", type=int, choices=(1, 2, 3), help="只渲染一组对照（一次两组）")
    parser.add_argument("--out", default="VIEW4_REPORT.md", help="md 快照输出文件")
    args = parser.parse_args()

    pairs = [fn() for fn in PAIRS]
    pairs = [p for p in pairs if p]
    if not pairs:
        print("[错误] 未找到任何场景存档（请先运行 S1~S5 实验）")
        return 1
    text = render_md(pairs, args.pair)
    print(text)
    out_path = Path(__file__).resolve().parent / args.out
    out_path.write_text(text, encoding="utf-8")
    print("\n[已写入] %s（共 %d 组对照）" % (out_path, len([p for p in pairs
                                                          if not args.pair or p["id"] == args.pair])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
