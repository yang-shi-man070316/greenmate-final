"""S1 单元/链路测试（无需 LLM Key / 无需联网）。

- 稳态数据准备：幂等、窗口 29~30℃、无持续升降、scenario=normal、统计解释；
- 结构化判断：stable / attention / model_disagreement（模型结果不修改）；
- 运行记录：save/load roundtrip、inspect 摘要回答两个问题；
- 完整链路（LLM 不可用时结构化判断仍完整保存）。

运行：python B07/S1/tests/test_s1.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
S1 = Path(__file__).resolve().parent.parent  # B07/S1
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT, S1):
    sys.path.insert(0, str(d))

from B02 import db as b02_db  # noqa: E402
from B05.tools import get_current_environment, get_environment_history  # noqa: E402

from judgment import build_judgment, trend_of  # noqa: E402
from prepare import ensure_stable_window, explain_stability  # noqa: E402
from records import load_run, make_run_id, save_run, summarize  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def main():
    results = []

    # 1. 稳态数据准备
    window, stats = ensure_stable_window()
    results.append(check("稳态窗口 6 个采样点", len(window) == 6, str(len(window))))
    results.append(check("温度 29~30℃ 小幅波动（含 ±0.4 噪声容差）",
                         28.5 <= stats["temperature"]["min"]
                         and stats["temperature"]["max"] <= 31.0
                         and 29.0 <= stats["temperature"]["mean"] <= 30.0
                         and stats["temperature"]["range"] <= 2.0,
                         "%.1f~%.1f mean=%.1f" % (stats["temperature"]["min"],
                                                  stats["temperature"]["max"],
                                                  stats["temperature"]["mean"])))
    results.append(check("温湿度无持续升降", abs(stats["temp_trend_c_per_3h"]) <= 0.5
                         and abs(stats["hum_trend_pct_per_3h"]) <= 3.0,
                         "temp_diff=%s hum_diff=%s" % (stats["temp_trend_c_per_3h"],
                                                       stats["hum_trend_pct_per_3h"])))
    results.append(check("光照正常（白天范围）且无扰动", stats["light"]["min"] > 10000
                         and stats["sim_scenarios"] == ["normal"], str(stats["sim_scenarios"])))
    results.append(check("稳定性解释文本存在", stats["stable"] and "无持续升降" in stats["explanation"]))
    results.append(check("追加幂等（再次调用不重复追加）", ensure_stable_window()[0][-1]["timestamp"]
                         == window[-1]["timestamp"]))
    # B02 库连续性抽查：追加段内相邻间隔 30 分钟
    conn = b02_db.connect()
    try:
        rows = b02_db.query_series(conn)
        tail = rows[-20:]
    finally:
        conn.close()
    from datetime import datetime, timedelta
    gaps = sum(1 for i in range(1, len(tail)) if
               datetime.strptime(tail[i]["timestamp"], "%Y-%m-%d %H:%M:%S")
               - datetime.strptime(tail[i - 1]["timestamp"], "%Y-%m-%d %H:%M:%S")
               != timedelta(minutes=30))
    results.append(check("B02 库追加后时间连续性", gaps == 0, "尾部 20 点断点数 %d" % gaps))

    # 2. 结构化判断
    current = get_current_environment()
    history = get_environment_history(3)
    pred_normal = {"predicted_attention": "NORMAL", "model_version": "b06-rf-v1",
                   "probability": {"NORMAL": 0.99, "WATCH": 0.01}}
    pred_watch = {"predicted_attention": "WATCH", "model_version": "b06-rf-v1",
                  "probability": {"NORMAL": 0.2, "WATCH": 0.8}}

    j = build_judgment(current, history, pred_normal)
    results.append(check("稳定数据 + NORMAL → verdict=stable", j["verdict"] == "stable", j["verdict"]))
    results.append(check("结构化字段齐全（当前状态/趋势/预测/证据/限制）",
                         all(k in j for k in ("current_state", "recent_trend", "predicted_attention",
                                              "evidence_status", "judgment_limits"))))

    j2 = build_judgment(current, history, pred_watch)
    results.append(check("稳定数据 + WATCH → model_disagreement（不修改模型结果）",
                         j2["verdict"] == "model_disagreement"
                         and j2["predicted_attention"] == "WATCH"
                         and j2["model_output_modified"] is False, j2["verdict"]))

    bad_history = {"status": "error", "source": "simulated_history",
                   "error": {"error_type": "no_data", "message": "无数据"}}
    j3 = build_judgment(current, bad_history, pred_normal)
    results.append(check("无历史数据 → inconclusive（不强行给结论）",
                         j3["verdict"] == "inconclusive", j3["verdict"]))

    # 趋势计算手工验证
    samples = [
        {"timestamp": "2026-10-20 13:30:00", "temperature": 29.5, "humidity": 46.0, "light": 52500, "sim_scenario": "normal"},
        {"timestamp": "2026-10-20 14:00:00", "temperature": 29.7, "humidity": 45.8, "light": 54000, "sim_scenario": "normal"},
        {"timestamp": "2026-10-20 14:30:00", "temperature": 29.9, "humidity": 45.6, "light": 54800, "sim_scenario": "normal"},
        {"timestamp": "2026-10-20 15:00:00", "temperature": 30.0, "humidity": 45.5, "light": 55000, "sim_scenario": "normal"},
        {"timestamp": "2026-10-20 15:30:00", "temperature": 29.8, "humidity": 45.7, "light": 54500, "sim_scenario": "normal"},
        {"timestamp": "2026-10-20 16:00:00", "temperature": 29.6, "humidity": 46.1, "light": 53500, "sim_scenario": "normal"},
    ]
    t = trend_of(samples)
    results.append(check("趋势计算：手工数据判定稳定", t["data_stable"] is True,
                         "temp_half_diff=%s" % t["temperature"]["half_diff"]))
    t2 = trend_of([{**s, "temperature": s["temperature"] + (3 if i >= 3 else 0)}
                   for i, s in enumerate(samples)])
    results.append(check("趋势计算：持续升温判定不稳定", t2["data_stable"] is False,
                         "temp_half_diff=%s" % t2["temperature"]["half_diff"]))

    # 3. 运行记录 roundtrip
    rid = make_run_id()
    record = {"run_id": rid, "created_at": "2026-10-20 00:00:00", "chain_status": "test",
              "step1_current_environment": current, "step2_recent_history_3h": history,
              "step3_model_prediction": pred_normal, "step4_structured_judgment": j,
              "step5_llm_explanation": {"status": "error", "error_type": "test",
                                        "message": "测试环境无 LLM"}}
    path = save_run(record)
    loaded = load_run(rid)
    results.append(check("运行记录 save/load roundtrip", loaded["run_id"] == rid
                         and loaded["step4_structured_judgment"]["verdict"] == "stable"))
    text = summarize(loaded)
    results.append(check("inspect 摘要回答两个问题",
                         "Q1 这次 GreenMate 看到了什么" in text
                         and "Q2 最后为什么说它比较稳定" in text))
    print("[记录文件] %s" % path)

    print("\nS1 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
