"""VIEW1 状态总览视图渲染器（只读）。

全局规则：只读取指定 run_id 已保存存档进行渲染——
禁止重跑实验、禁止重新拉取天气、禁止重新调用 LLM、禁止重新运行模型预测、不新增推理。

本模块只 import json/pathlib/re（无 LLM/模型/天气依赖），render() 为纯函数，
从代码层面保证刷新/重开视图不会发起任何新调用，结论与原始 run 完全一致。

用法（项目根目录）：
  python B07/VIEW/v1_overview/overview_render.py --run-id i3-20261031013638-f78ead
  python B07/VIEW/v1_overview/overview_render.py --run-id i3-xxx --out VIEW1_REPORT.md
"""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
RECORDS_DIR = ROOT / "B07" / "S5" / "run_records"

DEFAULT_RUN_ID = "i3-20261031013638-f78ead"

# verdict → 关注等级（只读映射，非新增推理）
VERDICT_LEVELS = {
    "attention_confirmed": ("高（需要重点关注）", "证据一致指向风险"),
    "attention_uncertain": ("中高（关注，存在分歧/不确定性）", "证据分歧，保留不确定性"),
    "attention_weather_missing": ("中高（关注，天气维度受限）", "天气证据缺失，判断边界收缩"),
    "attention_trend_prediction_normal": ("高（关注，趋势风险）", "历史升温风险，预测预计缓解"),
    "attention_trend_prediction_watch": ("高（需要重点关注）", "趋势与预测均指向风险"),
    "attention": ("高（需要重点关注）", "证据指向风险"),
    "stable": ("低（无需重点关注）", "状态稳定"),
    "current_only_limited": ("未知（证据不足）", "仅当前值，无法判断演化"),
}

READONLY_DECLARATION = (
    "本视图为只读渲染：未发起新的 LLM 调用、未重新运行模型预测、未重新拉取天气，"
    "未新增推理——全部内容来自存档中预生成的结构化结果。刷新/重开视图结论不变。")


def load_run(run_id):
    """只读加载存档（不 import 任何实验模块，避免任何副作用）。"""
    if not re.match(r"^[A-Za-z0-9_-]+$", run_id or ""):
        raise ValueError("非法 run_id：%s" % run_id)
    path = RECORDS_DIR / ("%s.json" % run_id)
    if not path.exists():
        available = sorted(p.name[:-5] for p in RECORDS_DIR.glob("i3-*.json"))
        raise FileNotFoundError("存档不存在：%s（可用 i3- 记录：%s）" % (run_id, available))
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_raw_observation(record):
    """从存档提取本次分析使用的原始观测数值（存档有什么就展示什么，缺失如实标注）。"""
    obs = {"temperature": None, "humidity": None, "light": None,
           "temperature_note": "", "humidity_note": "", "light_note": ""}
    e1 = next((e for e in record.get("adopted_evidence", [])
               if e.get("source_type") == "internal_history"), None)
    if e1:
        result = e1.get("result") or {}
        if result.get("temperature_last") is not None:
            obs["temperature"] = result["temperature_last"]
            obs["temperature_note"] = "窗口末点 %s" % (result.get("window", "?").split("~")[-1].strip()
                                                if result.get("window") else "?")
    # humidity/light：检查存档是否有观测快照字段
    snap = record.get("current_observation") or {}
    if snap.get("humidity") is not None:
        obs["humidity"] = snap["humidity"]
    else:
        obs["humidity_note"] = "本存档未存储湿度原始观测值"
    if snap.get("light") is not None:
        obs["light"] = snap["light"]
    else:
        obs["light_note"] = "本存档未存储光照原始观测值"
    return obs


def _extract_structured_state(record):
    """从存档提取预生成的结构化结果（当前环境状态/关注等级/近期趋势/下一窗口预测/证据完整度）。"""
    judgment = record.get("judgment") or {}
    e2 = next((e for e in record.get("adopted_evidence", [])
               if e.get("source_type") == "ml_prediction"), None)
    e1 = next((e for e in record.get("adopted_evidence", [])
               if e.get("source_type") == "internal_history"), None)
    adopted = record.get("adopted_evidence", [])
    missing = record.get("missing_evidence", [])
    level, level_note = VERDICT_LEVELS.get(judgment.get("verdict"), ("—", "—"))
    state = {
        "verdict": judgment.get("verdict", "—"),
        "attention_level": level,
        "attention_note": level_note,
        "state_summary": judgment.get("verdict_note", "—"),
        "trend": (e1 or {}).get("result", {}).get("trend", "未存储"),
        "trend_meaning": "已发生事实（B02 历史时序）",
        "prediction": ((e2 or {}).get("result") or {}).get("predicted_attention", "未存储"),
        "prediction_probability": ((e2 or {}).get("result") or {}).get("probability", {}),
        "prediction_meaning": "模型对下一窗口的推断（B06，不是已发生事实）",
        "evidence_complete": "%d/%d 有效%s" % (
            len(adopted), len(adopted) + len(missing),
            "" if not missing else "，缺失：%s" % ", ".join(
                m.get("evidence_id", "?") for m in missing)),
    }
    return state


def render(record):
    """纯函数渲染总览视图（输入存档字典，输出视图文本）。"""
    obs = _extract_raw_observation(record)
    st = _extract_structured_state(record)
    lines = [
        "=" * 64,
        "GreenMate VIEW1 · 状态总览视图",
        "=" * 64,
        "run_id: %s | 创建于 %s | mode: %s" % (
            record.get("run_id"), record.get("created_at"), record.get("mode")),
        "",
        "【原始观测数值】（本次分析使用的环境数据，直接取自存档）",
    ]
    if obs["temperature"] is not None:
        lines.append("  温度：%s℃（%s）" % (obs["temperature"], obs["temperature_note"]))
    else:
        lines.append("  温度：未存储在存档中")
    if obs["humidity"] is not None:
        lines.append("  湿度：%s%%" % obs["humidity"])
    else:
        lines.append("  湿度：%s" % obs["humidity_note"])
    if obs["light"] is not None:
        lines.append("  光照：%s lux" % obs["light"])
    else:
        lines.append("  光照：%s" % obs["light_note"])
    lines += [
        "",
        "【系统理解后的状态】（由原始 run 的结构化判定预生成，本视图只读取不重算）",
        "  判定 verdict：%s" % st["verdict"],
        "  当前环境状态：%s" % st["state_summary"],
        "  关注等级：%s（%s）" % (st["attention_level"], st["attention_note"]),
        "  近期趋势：%s —— %s" % (st["trend"], st["trend_meaning"]),
        "  下一时间窗口预测：%s（概率 %s）—— %s" % (
            st["prediction"], st["prediction_probability"], st["prediction_meaning"]),
        "  证据完整度：%s" % st["evidence_complete"],
        "",
        "【一句话回答】当前番茄生长环境处于：%s" % st["state_summary"],
        "",
        READONLY_DECLARATION,
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="VIEW1 状态总览视图（只读渲染）")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="读取的 run_id（默认任务书指定）")
    parser.add_argument("--out", help="将视图写入文件（如 VIEW1_REPORT.md）")
    args = parser.parse_args()

    record = load_run(args.run_id)
    text = render(record)
    print(text)
    if args.out:
        out_path = Path(__file__).resolve().parent / args.out
        out_path.write_text(text, encoding="utf-8")
        print("\n[已写入] %s" % out_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
