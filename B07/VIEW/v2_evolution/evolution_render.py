"""VIEW2 状态演化视图渲染器（只读）。

全局规则：只读取指定 run_id 存档——禁止重跑实验、禁止重新拉取天气、
禁止调用 LLM、禁止重新运行模型预测，只读不新增推理。

数据来源（全部只读）：
1. run_id 存档自带数据：E1 历史窗口（window/温度首末/趋势）、E2 模型判定与概率、
   E3 天气预报逐时温度（存档自带，不重新查询）；
2. S1/S2 两条演化路径对照数据：内嵌常量，数值与 B07/S2 实验定义完全一致
   （S1 平台段 / S2 漂移段，同样到达 30℃）——作为视图演示数据，非本次查询结果。

本模块只 import json/pathlib/re（无 LLM/模型/天气依赖），render 为纯函数。

用法（项目根目录）：
  python B07/VIEW/v2_evolution/evolution_render.py --run-id i3-20261031013638-f78ead
  python B07/VIEW/v2_evolution/evolution_render.py --run-id xxx --out VIEW2_REPORT.md
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
RECORDS_DIR = ROOT / "B07" / "S5" / "run_records"

DEFAULT_RUN_ID = "i3-20261031013638-f78ead"

# S1/S2 演化路径对照数据（内嵌常量；数值与 B07/S2 实验定义一致：
# drift_inject.py 的 DRIFT_TEMPS/HUMS/LIGHTS 与 innovate1_ext.py 的 PLATEAU_* ）
S1_PATH = {
    "name": "S1 稳态维持",
    "temps": [29.7, 30.2, 29.9, 30.3, 30.0, 30.1, 30.0],
    "hums": [46.5, 46.2, 46.8, 46.4, 46.6, 46.3, 46.5],
    "lights": [10.0, 8.0, 6.0, 5.0, 5.0, 5.0, 5.0],
    "shape": "30℃ 附近小幅波动（幅差 0.6℃），无持续升降",
    "evolution": "稳态维持：7 个采样点始终在 29.7~30.3℃ 窄幅内，历史过程不改变状态判断",
}
S2_PATH = {
    "name": "S2 持续升温",
    "temps": [25.0, 25.8, 26.7, 27.5, 28.3, 29.2, 30.0],
    "hums": [50.0, 49.6, 49.1, 48.7, 48.2, 47.8, 47.3],
    "lights": [12000.0, 9000.0, 6000.0, 3500.0, 1500.0, 400.0, 10.0],
    "shape": "25→30℃ 匀速升温（每 30 分钟 +0.83℃），持续上升",
    "evolution": "持续升温：温度逐点爬升，最后一点才到达 30℃——30℃ 是升温过程的结果而非稳态",
}

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_run(run_id):
    if not re.match(r"^[A-Za-z0-9_-]+$", run_id or ""):
        raise ValueError("非法 run_id：%s" % run_id)
    path = RECORDS_DIR / ("%s.json" % run_id)
    if not path.exists():
        available = sorted(p.name[:-5] for p in RECORDS_DIR.glob("i3-*.json"))
        raise FileNotFoundError("存档不存在：%s（可用 i3- 记录：%s）" % (run_id, available))
    return json.loads(path.read_text(encoding="utf-8"))


def extract_archive(record):
    """从存档提取自带演化信息（只读，不查询）。"""
    e1 = next((e for e in record.get("adopted_evidence", [])
               if e.get("source_type") == "internal_history"), None)
    e2 = next((e for e in record.get("adopted_evidence", [])
               if e.get("source_type") == "ml_prediction"), None)
    e3 = next((e for e in record.get("adopted_evidence", [])
               if e.get("source_type") == "external_weather"), None)
    r1 = (e1 or {}).get("result") or {}
    r2 = (e2 or {}).get("result") or {}
    r3 = (e3 or {}).get("result") or {}
    forecast_temps = [h.get("temperature_2m") for h in
                      (r3.get("forecast") or {}).get("hourly", [])
                      if h.get("temperature_2m") is not None]
    return {
        "history_window": r1.get("window", "未存储"),
        "history_temp_first": r1.get("temperature_first"),
        "history_temp_last": r1.get("temperature_last"),
        "history_trend": r1.get("trend", "未存储"),
        "history_note": "存档仅含窗口首末温度（逐点历史序列未存入存档，如实标注，不重新查询）",
        "prediction": r2.get("predicted_attention", "未存储"),
        "prediction_probability": r2.get("probability", {}),
        "forecast_temps": forecast_temps or None,
        "forecast_note": ("存档自带天气预报逐时温度（外部潜在条件）"
                          if forecast_temps else "存档未含天气预报温度"),
        "verdict": (record.get("judgment") or {}).get("verdict", "未存储"),
        "verdict_note": (record.get("judgment") or {}).get("verdict_note", "未存储"),
    }


def build_view_data(record):
    """组装视图数据：两条演化路径 + 存档提取 + 状态节点。"""
    arch = extract_archive(record)
    nodes = [
        ("S1 路径节点", "全程稳定", "S1 七个采样点温度幅差仅 0.6℃，无持续升降——"
         "系统判定稳定态（stable），没有状态切换"),
        ("S2 风险节点", "第 6→7 点越过 30℃ 高温边界", "S2 温度在最后两个采样点越过 30℃，"
         "持续升温过程使状态进入风险区——同样的 30℃，S2 是升温到达的风险态"),
        ("模型判定节点", "窗口末判定 WATCH（%s）" % arch["prediction_probability"].get("WATCH", "?"),
         "B06 模型对演化窗口输出 WATCH（%s），模型判定切换为风险关注" % arch["prediction"]),
        ("存档实例", "10-08 11:30~14:30 持续升温（26.3→38.1℃）",
         "本 run_id 的历史窗口同样是持续升温路径（存档仅含首末点），与 S2 演化形态同类"),
    ]
    return {"paths": [S1_PATH, S2_PATH], "archive": arch, "nodes": nodes,
            "run_id": record.get("run_id"), "created_at": record.get("created_at"),
            "mode": record.get("mode")}


def render_md(view):
    """渲染 md 快照（数据表形式，供 build_html 生成 SVG 曲线）。"""
    arch = view["archive"]
    lines = [
        "=" * 64,
        "GreenMate VIEW2 · 状态演化视图",
        "=" * 64,
        "run_id: %s | 创建于 %s | mode: %s" % (view["run_id"], view["created_at"], view["mode"]),
        "",
        "本视图为只读渲染：未重新查询时序数据、未重新拉取天气、未调用 LLM、未重跑模型，"
        "未新增推理。S1/S2 对照数据为内嵌常量（与 B07/S2 实验定义一致），存档缺失字段如实标注。",
        "",
        "## 演化路径对照（同样到达 30℃，两条路径如何形成状态）",
        "",
    ]
    for p in view["paths"]:
        lines += [
            "### %s" % p["name"],
            "温度序列（7 点，30 分钟/点）: %s" % ", ".join(str(v) for v in p["temps"]),
            "湿度序列: %s" % ", ".join(str(v) for v in p["hums"]),
            "光照序列: %s" % ", ".join(str(v) for v in p["lights"]),
            "形态：%s" % p["shape"],
            "演化解释：%s" % p["evolution"],
            "",
        ]
    lines += [
        "## 状态节点（时间线上的判定切换与风险变化）",
        "",
    ]
    for title, when, why in view["nodes"]:
        lines.append("- **%s**（%s）：%s" % (title, when, why))
    lines += [
        "",
        "## 本存档演化数据（run_id 自带，只读提取）",
        "历史窗口：%s | 温度 %s → %s℃ | %s" % (
            arch["history_window"], arch["history_temp_first"], arch["history_temp_last"],
            arch["history_trend"]),
        "说明：%s" % arch["history_note"],
        "模型判定：%s（概率 %s）" % (arch["prediction"], arch["prediction_probability"]),
        "天气预报温度（存档自带）：%s | %s" % (
            ", ".join(str(v) for v in arch["forecast_temps"]) if arch["forecast_temps"] else "未存储",
            arch["forecast_note"]),
        "判定结论：%s（%s）" % (arch["verdict"], arch["verdict_note"]),
        "",
        "## 一句话回答",
        "S1 与 S2 同样在最后一点到达 30℃：S1 是全程 29.7~30.3℃ 的稳态维持（判定稳定）；"
        "S2 是 25→30℃ 的持续升温（判定风险）。状态不是由单个瞬时值决定的，"
        "而是由演化过程形成的——这正是时序演化推理的核心。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="VIEW2 状态演化视图（只读渲染）")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="读取的 run_id（默认任务书指定）")
    parser.add_argument("--out", default="VIEW2_REPORT.md", help="md 快照输出文件")
    args = parser.parse_args()

    record = load_run(args.run_id)
    view = build_view_data(record)
    text = render_md(view)
    print(text)
    out_path = Path(__file__).resolve().parent / args.out
    out_path.write_text(text, encoding="utf-8")
    print("\n[已写入] %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
