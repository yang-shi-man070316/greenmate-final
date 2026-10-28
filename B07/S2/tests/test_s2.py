"""S2 漂移对照实验测试（无需 LLM Key / 无需联网）。

- 漂移注入：7 点 25→30℃ 匀速升温、幂等、B02 连续性；
- 趋势识别：系统仅凭时序历史自主判定漂移段「不稳定」（无任何人工提示）；
- 结构化判断：漂移段 + 模型 NORMAL → attention；+ WATCH → attention；
- 对照报告生成（mock 记录）。

运行：python B07/S2/tests/test_s2.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
S2 = Path(__file__).resolve().parent.parent  # B07/S2
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT, S2):
    sys.path.insert(0, str(d))

from B02 import db as b02_db  # noqa: E402
from B05.tools import get_current_environment  # noqa: E402
from B07.S1.judgment import build_judgment, trend_of  # noqa: E402

from drift_inject import DRIFT_TEMPS, inject_drift, is_drift_injected  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def main():
    results = []

    # 1. 漂移段注入
    injected, rows = inject_drift()
    conn = b02_db.connect()
    try:
        injected_now = is_drift_injected(conn)
    finally:
        conn.close()
    results.append(check("漂移段注入成功且幂等检测生效", len(rows) == 7 and injected_now,
                         "injected=%s, 7点=%s" % (injected, len(rows))))
    temps = [r["temperature"] for r in rows]
    results.append(check("温度 25→30℃ 匀速升温（每点 +0.83℃，1位小数下为 0.8/0.9 交替）",
                         abs(temps[0] - 25.0) < 0.01 and abs(temps[-1] - 30.0) < 0.01
                         and all(0.7 <= temps[i + 1] - temps[i] <= 1.0
                                 for i in range(len(temps) - 1)),
                         str(temps)))
    results.append(check("湿度/光照在正常范围且 sim_scenario=normal",
                         all(40 <= r["humidity"] <= 55 for r in rows)
                         and all(0 <= r["light"] <= 120000 for r in rows)
                         and all(r["sim_scenario"] == "normal" for r in rows)))

    # 2. 趋势自主识别（无人工提示）
    conn = b02_db.connect()
    try:
        tail = b02_db.query_series(conn)[-7:]
    finally:
        conn.close()
    t = trend_of(tail)
    results.append(check("系统自主识别持续升温（half_diff > +2℃）",
                         t["temperature"]["half_diff"] > 2.0,
                         "half_diff=%s" % t["temperature"]["half_diff"]))
    results.append(check("漂移段判定 data_stable=False", t["data_stable"] is False))

    # 3. 结构化判断
    current = get_current_environment()
    history = {"status": "ok", "source": "simulated_history",
               "data": {"samples": tail}}
    pred_normal = {"predicted_attention": "NORMAL", "model_version": "b06-rf-v1",
                   "probability": {"NORMAL": 0.9, "WATCH": 0.1}}
    pred_watch = {"predicted_attention": "WATCH", "model_version": "b06-rf-v1",
                  "probability": {"NORMAL": 0.1, "WATCH": 0.9}}
    j1 = build_judgment(current, history, pred_normal)
    results.append(check("漂移数据 + 模型 NORMAL → attention（识别风险）",
                         j1["verdict"] == "attention", j1["verdict"]))
    j2 = build_judgment(current, history, pred_watch)
    results.append(check("漂移数据 + 模型 WATCH → attention（模型结果不修改）",
                         j2["verdict"] == "attention" and j2["predicted_attention"] == "WATCH"
                         and j2["model_output_modified"] is False, j2["verdict"]))

    # 4. 对照报告生成（mock 两组记录）
    from report import attention_level, build_report
    s1_record = {
        "run_id": "s1-mock", "created_at": "mock", "experiment": None,
        "step4_structured_judgment": {
            "verdict": "stable",
            "recent_trend": {"available": True, "window": "13:30~16:30",
                             "temperature": {"min": 29.0, "max": 30.4, "half_diff": 0.4},
                             "humidity": {"min": 43.8, "max": 47.0, "half_diff": -0.25}},
        },
        "step3_model_prediction": {"predicted_attention": "NORMAL",
                                   "model_version": "b06-rf-v1",
                                   "probability": {"NORMAL": 1.0, "WATCH": 0.0}},
        "step5_llm_explanation": {"status": "success", "answer": "mock S1"},
    }
    s2_record = {
        "run_id": "s1-mock2", "created_at": "mock", "experiment": "S2_drift",
        "step4_structured_judgment": {
            "verdict": "attention",
            "recent_trend": {"available": True, "window": "17:00~20:00",
                             "temperature": {"min": 25.0, "max": 30.0, "half_diff": 2.92},
                             "humidity": {"min": 47.3, "max": 50.0, "half_diff": -1.7}},
        },
        "step3_model_prediction": {"predicted_attention": "WATCH",
                                   "model_version": "b06-rf-v1",
                                   "probability": {"NORMAL": 0.4, "WATCH": 0.6}},
        "step5_llm_explanation": {"status": "success", "answer": "mock S2"},
    }
    report_text = build_report(s1_record, s2_record, Path("s1.json"), Path("s2.json"))
    results.append(check("报告含差异对比表（瞬时/趋势/预测/判定/关注等级）",
                         all(k in report_text for k in ("瞬时温度", "持续上升漂移", "风险判定",
                                                        "关注等级", "S1 基线", "S2 漂移"))))
    results.append(check("关注等级映射正确",
                         attention_level("stable") == "低（无需重点关注）"
                         and "需要重点关注" in attention_level("attention")))

    print("\nS2 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
