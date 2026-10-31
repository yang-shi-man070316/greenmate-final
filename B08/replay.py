"""B08 回归回放模式：按 scenario_id 加载快照证据，输入完全固定。

原则：回放不查询任何数据源、不调用 LLM/模型/天气、不重算判定——
只读加载 scenarios/ 快照并输出固定回放报告；重复运行输出完全一致。

用法（项目根目录）：
  python B08/replay.py --scenario b08_s3_weather
  python B08/replay.py --list            # 列出可用场景
  python B08/replay.py --scenario xxx --check    # 附加一致性自检（字段完整性）
"""

import argparse
import json
import sys
from pathlib import Path

B08_DIR = Path(__file__).resolve().parent
SCENARIOS_DIR = B08_DIR / "scenarios"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def list_scenarios():
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


def load_snapshot(scenario_id):
    if not scenario_id or not scenario_id.startswith("b08_"):
        raise ValueError("非法 scenario_id：%s（格式 b08_*，可用：%s）" % (
            scenario_id, list_scenarios()))
    path = SCENARIOS_DIR / ("%s.json" % scenario_id)
    if not path.exists():
        raise FileNotFoundError("场景快照不存在：%s（可用：%s）" % (scenario_id, list_scenarios()))
    return json.loads(path.read_text(encoding="utf-8"))


def check_snapshot(snapshot):
    """快照一致性自检：字段完整性 + 版本标记。返回问题列表。"""
    problems = []
    for field in ("scenario_id", "source_run_id", "app_version", "model_version",
                  "observation", "history_series", "judgment_snapshot",
                  "frozen_at", "fixed_question"):
        if snapshot.get(field) in (None, "", []):
            problems.append("缺少字段：%s" % field)
    if snapshot.get("app_version") != "B08_baseline_01":
        problems.append("app_version 非基线：%s" % snapshot.get("app_version"))
    if snapshot.get("model_version") != "b06-rf-v1":
        problems.append("model_version 非锁定版本：%s" % snapshot.get("model_version"))
    if not snapshot.get("frozen"):
        problems.append("快照未标记 frozen")
    return problems


def render_replay(snapshot):
    """渲染固定回放报告（两次运行输出完全一致）。"""
    hist = snapshot["history_series"]
    temps = [p["temperature"] for p in hist]
    judgment = snapshot["judgment_snapshot"]
    weather = snapshot["weather_evidence"]
    lines = [
        "=" * 64,
        "GreenMate B08 回归回放（replay）",
        "=" * 64,
        "scenario_id: %s（%s）" % (snapshot["scenario_id"], snapshot["name"]),
        "app_version: %s | model_version: %s" % (snapshot["app_version"],
                                                  snapshot["model_version"]),
        "源 run_id: %s（%s，冻结于 %s）" % (snapshot["source_run_id"],
                                             snapshot["source_module"],
                                             snapshot["frozen_at"]),
        "",
        "【固定输入（快照证据，回放不再查询任何数据源）】",
        "  观测：%.1f℃ / %.1f%% / %.0f lux（%s）" % (
            snapshot["observation"]["temperature"], snapshot["observation"]["humidity"],
            snapshot["observation"]["light"], snapshot["observation"]["observed_at"]),
        "  历史时序：%d 点（%s ~ %s，温度 %.1f → %.1f℃）" % (
            len(hist), hist[0]["timestamp"], hist[-1]["timestamp"],
            temps[0], temps[-1]),
    ]
    if weather:
        if weather.get("status") == "unavailable":
            lines.append("  天气证据：不可用（%s）" % weather.get("reason"))
        else:
            hourly = weather.get("hourly") or []
            lines.append("  天气证据：%s，%d 小时预报（provider=%s）" % (
                weather.get("status"), len(hourly), weather.get("provider")))
    else:
        lines.append("  天气证据：本场景无天气证据")
    if snapshot["knowledge_citation"]:
        lines.append("  引用知识：%s" % ", ".join(
            "%s(%s)" % (c["id"], c["source"]) for c in snapshot["knowledge_citation"]))
    else:
        lines.append("  引用知识：本场景无知识证据")
    lines += [
        "",
        "【判定快照（冻结时固化，回放不重算）】",
        "  verdict: %s" % judgment["verdict"],
        "  说明: %s" % judgment["verdict_note"],
        "",
        "【回放声明】本输出仅由快照文件渲染：未查询 B02、未调用天气 API、未运行模型、"
        "未调用 LLM；重复运行输出完全一致（回归验证可用）。",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="B08 回归回放模式")
    parser.add_argument("--scenario", help="scenario_id（b08_*）")
    parser.add_argument("--list", action="store_true", help="列出可用场景")
    parser.add_argument("--check", action="store_true", help="附加快照一致性自检")
    args = parser.parse_args()

    if args.list:
        print("可用场景：%s" % ", ".join(list_scenarios()))
        return 0
    if not args.scenario:
        parser.print_help()
        return 1

    snapshot = load_snapshot(args.scenario)
    print(render_replay(snapshot))
    if args.check:
        problems = check_snapshot(snapshot)
        if problems:
            print("\n[自检] FAIL：%s" % problems)
            return 1
        print("\n[自检] PASS：快照字段完整，版本标记正确（%s / %s）" % (
            snapshot["app_version"], snapshot["model_version"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
