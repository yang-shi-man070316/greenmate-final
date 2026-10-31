"""B08 基线冻结：将 S1~S5 实验场景固化为带 scenario_id 的固定快照。

原则：B08 不新增功能、不修改 B07 创新机制——冻结只是从已存在的 B07 存档与 B02
数据中一次性读取并固化快照（冻结后回放不再查询任何数据源）。

产出：
- scenarios/b08_<scene>.json（五个场景快照，绑定 scenario_id）；
- BASELINE_INFO.md（版本基线说明：app_version / model_version / 知识资料版本）。

用法（项目根目录）：
  python B08/freeze.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for d in (ROOT / "B07" / "S5", ROOT / "B07" / "S4", ROOT / "B07" / "S3",
          ROOT / "B07" / "S2", ROOT / "B07" / "S1", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B02 import db as b02_db  # noqa: E402

B08_DIR = Path(__file__).resolve().parent
SCENARIOS_DIR = B08_DIR / "scenarios"

# 版本锁定（本轮验证全程固定，禁止动态切换）
APP_VERSION = "B08_baseline_01"
MODEL_VERSION = "b06-rf-v1"
KNOWLEDGE_VERSION = "b04_kb_v1（K01~K09，knowledge_base.json version 1.0）"
FIXED_QUESTION = ("结合全部可用证据，分析当前番茄生长环境风险："
                  "哪些方面可以判断，哪些方面因证据受限无法判断？")

SCENARIOS = [
    {
        "id": "b08_s1_steady",
        "name": "S1 稳态基线",
        "source": "B07/S1",
        "run_id": "s1-20261020212515-1d9ba6",
        "history_window": ("2026-10-20 13:30:00", "2026-10-20 16:30:00"),
        "weather": None,
    },
    {
        "id": "b08_s2_drift",
        "name": "S2 渐进漂移",
        "source": "B07/S2",
        "run_id": "s2-20261021221953-964d11",
        "history_window": ("2026-10-20 17:00:00", "2026-10-20 20:00:00"),
        "weather": None,
    },
    {
        "id": "b08_s3_weather",
        "name": "S3 天气叠加",
        "source": "B07/S3",
        "run_id": "s3-20261022194350-9457a8",
        "history_window": ("2026-10-08 11:30:00", "2026-10-08 14:30:00"),
        "weather": "from_record",
    },
    {
        "id": "b08_s4_multi",
        "name": "S4 多源分歧",
        "source": "B07/S4",
        "run_id": "s4-20261022202715-3741cc",
        "history_window": ("2026-10-08 11:30:00", "2026-10-08 14:30:00"),
        "weather": "from_evidence",
    },
    {
        "id": "b08_s5_degraded",
        "name": "S5 证据退化（天气缺失）",
        "source": "B07/S5",
        "run_id": "s5-20261028153511-cd8ae2",
        "history_window": ("2026-10-08 11:30:00", "2026-10-08 14:30:00"),
        "weather": "missing",
    },
]

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_source_record(scene):
    """加载对应 B07 存档（只读）。"""
    rec_dir = ROOT / scene["source"] / "run_records"
    path = rec_dir / ("%s.json" % scene["run_id"])
    if not path.exists():
        available = sorted(p.name[:-5] for p in rec_dir.glob("*.json"))
        raise FileNotFoundError("源存档不存在：%s（%s 可用记录：%s）" % (
            path, scene["source"], available[:8]))
    return json.loads(path.read_text(encoding="utf-8"))


def judgment_of(record):
    return (record.get("structured_judgment")
            or record.get("step4_structured_judgment")
            or record.get("judgment") or {})


def extract_weather(scene, record):
    """固化天气证据快照（有则存内容，缺失则存 unavailable 状态）。"""
    if scene["weather"] is None:
        return None
    if scene["weather"] == "missing":
        return {"status": "unavailable",
                "reason": "天气证据调用失败（无未来天气数据），判断边界收缩"}
    wf = record.get("weather_forecast")
    if wf:
        data = wf.get("data") or wf
        hourly = (data.get("forecast") or {}).get("hourly") or []
        return {"status": wf.get("status"), "provider": wf.get("provider"),
                "forecast_time": data.get("forecast_time"),
                "hourly": hourly}
    e3 = next((e for e in record.get("adopted_evidence", []) + record.get("evidence", [])
               if e.get("source_type") == "external_weather"), None)
    if e3:
        result = e3.get("result") or {}
        hourly = (result.get("forecast") or {}).get("hourly") or []
        return {"status": e3.get("status"), "provider": e3.get("provider"),
                "forecast_time": e3.get("forecast_time"), "hourly": hourly}
    return None


def extract_knowledge(record):
    """固化引用知识快照（citation）。"""
    e4 = next((e for e in record.get("adopted_evidence", []) + record.get("evidence", [])
               if e.get("source_type") == "local_knowledge"), None)
    if not e4:
        return []
    citation = e4.get("citation") or []
    segments = (e4.get("result") or {}).get("segments") or []
    return [{"id": c.get("id"), "source": c.get("source"),
             "topic": next((s.get("topic") for s in segments if s.get("id") == c.get("id")), "")}
            for c in citation]


def freeze_scene(scene, history_rows):
    """生成单个场景快照。"""
    record = load_source_record(scene)
    judgment = judgment_of(record)
    last = history_rows[-1]
    snapshot = {
        "scenario_id": scene["id"],
        "name": scene["name"],
        "source_module": scene["source"],
        "source_run_id": scene["run_id"],
        "app_version": APP_VERSION,
        "model_version": MODEL_VERSION,
        "knowledge_version": KNOWLEDGE_VERSION,
        "frozen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fixed_question": FIXED_QUESTION,
        "observation": {
            "temperature": last["temperature"],
            "humidity": last["humidity"],
            "light": last["light"],
            "observed_at": last["timestamp"],
        },
        "history_series": history_rows,
        "weather_evidence": extract_weather(scene, record),
        "knowledge_citation": extract_knowledge(record),
        "judgment_snapshot": {
            "verdict": judgment.get("verdict"),
            "verdict_note": judgment.get("verdict_note"),
        },
        "frozen": True,
    }
    return snapshot


def freeze_all():
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    conn = b02_db.connect()
    try:
        for scene in SCENARIOS:
            start, end = scene["history_window"]
            rows = b02_db.query_series(conn, start, end)
            if len(rows) < 7:
                raise RuntimeError("B02 缺少场景 %s 的历史窗口（%s ~ %s，仅 %d 点）" % (
                    scene["id"], start, end, len(rows)))
            snapshot = freeze_scene(scene, rows)
            out = SCENARIOS_DIR / ("%s.json" % scene["id"])
            out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print("[冻结] %s → %s（历史 %d 点，判定=%s）" % (
                scene["id"], out.name, len(rows),
                snapshot["judgment_snapshot"]["verdict"]))
    finally:
        conn.close()

    write_baseline_info()


def write_baseline_info():
    lines = [
        "# GreenMate B08 基线版本说明（BASELINE_INFO）",
        "",
        "- 冻结时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "## 版本标记（本轮验证全程固定，禁止动态切换）",
        "",
        "| 版本项 | 值 |",
        "| --- | --- |",
        "| app_version | **%s** |" % APP_VERSION,
        "| model_version | **%s**（B06 已保存模型，本轮不重训、不切换） |" % MODEL_VERSION,
        "| 知识资料版本 | %s |" % KNOWLEDGE_VERSION,
        "| 固定提问 | %s |" % FIXED_QUESTION,
        "",
        "## 冻结场景清单（scenarios/，每个绑定 scenario_id，支持按 id 加载回放）",
        "",
        "| scenario_id | 场景 | 来源模块 | 源 run_id | 判定快照 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for scene in SCENARIOS:
        snap = json.loads((SCENARIOS_DIR / ("%s.json" % scene["id"]))
                          .read_text(encoding="utf-8"))
        lines.append("| %s | %s | %s | `%s` | %s |" % (
            scene["id"], scene["name"], scene["source"], scene["run_id"],
            snap["judgment_snapshot"]["verdict"]))
    lines += [
        "",
        "## 两种运行模式",
        "",
        "- **真实链路模式**（live）：实时调用天气 API、B06 模型、LLM，验证链路与异常退化；",
        "- **回归回放模式**（replay）：加载 scenarios/ 快照证据，输入完全固定，"
        "重复运行条件一致（不查询任何数据源、不调用 LLM/模型/天气）。",
        "",
        "## 冻结原则",
        "",
        "- B08 不新增功能、不修改 B07 已完成的创新机制；",
        "- 本文件与快照由 python B08/freeze.py 生成；重新冻结前请确认 B07 基线未变化。",
        "",
    ]
    (B08_DIR / "BASELINE_INFO.md").write_text("\n".join(lines), encoding="utf-8")
    print("[生成] BASELINE_INFO.md")


def main():
    freeze_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
