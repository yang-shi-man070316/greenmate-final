"""创新点1 对照验证实验测试（无需 LLM Key / 无需联网）。

- S2 漂移段装载：当前值 ≈30℃、历史 25→30℃ 升温；
- 三组判定：current_only_limited / attention_trend / attention_trend_prediction_*；
- 趋势与预测区分（judge 的 verdict_note 语义）；
- LLM prompt：统一提问 + 两块式 + 趋势/预测区分约束；
- 报告生成（mock 三组记录）+ 三个问题回答；
- run_id i1- 前缀 + 存档读写。

运行：python B07/S1/tests/test_innovate1.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
S1 = Path(__file__).resolve().parent.parent  # B07/S1
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT, S1):
    sys.path.insert(0, str(d))

from innovate1 import (FIXED_QUESTION, MODES, SYSTEM_PROMPT,  # noqa: E402
                       _answer_three_questions, generate_report, judge,
                       load_drift_window, load_prediction, load_run,
                       make_run_id, save_run)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def main():
    results = []

    # 1. S2 漂移段装载
    history, current, points6 = load_drift_window()
    results.append(check("当前观测 ≈30℃（S2 漂移段末点）",
                         29.5 <= current["temperature"] <= 30.5,
                         "%.1f℃" % current["temperature"]))
    results.append(check("历史 7 点：25→30℃ 匀速升温",
                         len(history) == 7 and history[0]["temperature"] < 26
                         and history[-1]["temperature"] >= 29.5
                         and history[-1]["temperature"] - history[0]["temperature"] >= 4.0,
                         "%.1f→%.1f" % (history[0]["temperature"], history[-1]["temperature"])))
    prediction = load_prediction()
    results.append(check("B06 预测输出含 predicted_attention/model_version",
                         prediction["predicted_attention"] in ("NORMAL", "WATCH")
                         and prediction["model_version"] == "b06-rf-v1",
                         str(prediction["predicted_attention"])))

    # 2. 三组判定
    j1 = judge("run_current_only", current, [], None)
    results.append(check("组1 仅当前值 → current_only_limited（无法判断演化方向）",
                         j1["verdict"] == "current_only_limited"
                         and "无法判断演化方向" in j1["verdict_note"], j1["verdict"]))
    j2 = judge("run_with_history", current, history, None)
    results.append(check("组2 +历史 → attention_trend（识别已发生的持续升温）",
                         j2["verdict"] == "attention_trend"
                         and "已发生" in j2["verdict_note"], j2["verdict"]))
    j3 = judge("run_with_history_prediction", current, history, prediction)
    results.append(check("组3 +预测 → verdict 含 trend 与 prediction 双维度",
                         j3["verdict"].startswith("attention_trend_prediction_"),
                         j3["verdict"]))
    results.append(check("趋势与预测严格区分（note 语义：历史=已发生、预测=预计）",
                         "已发生" in j3["verdict_note"]
                         and ("预计" in j3["verdict_note"] or "预测" in j3["verdict_note"]),
                         j3["verdict_note"]))
    results.append(check("三组 verdict 互不相同（证据恢复带来判定演化）",
                         len({j1["verdict"], j2["verdict"], j3["verdict"]}) == 3,
                         "%s / %s / %s" % (j1["verdict"], j2["verdict"], j3["verdict"])))

    # 3. LLM 约束
    results.append(check("统一固定提问与任务书一致",
                         "结合全部可用证据" in FIXED_QUESTION and "证据受限" in FIXED_QUESTION))
    results.append(check("prompt 强制两块 + 趋势/预测区分 + 禁止混为一谈",
                         "可判断内容" in SYSTEM_PROMPT and "受限说明" in SYSTEM_PROMPT
                         and "已经发生" in SYSTEM_PROMPT and "禁止混为一谈" in SYSTEM_PROMPT))

    # 4. 报告生成（mock 三组记录）
    mock = []
    for i, mode in enumerate(MODES):
        rid = make_run_id()
        llm_answer = ("【可判断内容】%s 的可判断内容…\n【受限说明】%s 的受限说明…" % (mode, mode))
        record = {
            "run_id": rid, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode, "experiment": "innovate1",
            "current_observation": {"timestamp": "2026-10-20 20:00:00", "temperature": 30.0,
                                    "humidity": 47.3, "light": 10.0},
            "history_samples": history if mode != "run_current_only" else None,
            "prediction": prediction if mode == "run_with_history_prediction" else None,
            "judgment": [j1, j2, j3][i],
            "llm_explanation": {"status": "success", "answer": llm_answer},
        }
        path = save_run(record)
        mock.append(record)
        # 写临时报告用记录（find_latest 会读取 run_records，直接用 mock 记录生成报告文本）
    q1, q2, q3 = _answer_three_questions(mock[0], mock[1], mock[2])
    results.append(check("报告三问：Q1 静态判断 / Q2 演化过程 / Q3 下一窗口",
                         "静态判断" in q1 and "演化" in q2 or "持续升温" in q2
                         and "下一窗口" in q3,
                         ""))
    results.append(check("报告三问均绑定对应组 verdict",
                         mock[0]["judgment"]["verdict"] in q1
                         and mock[1]["judgment"]["verdict"] in q2
                         and mock[2]["judgment"]["verdict"] in q3))

    # 5. run_id 与存档
    rid = make_run_id()
    results.append(check("run_id 为 i1- 前缀", bool(re.match(r"^i1-\d{14}-[0-9a-f]{6}$", rid)), rid))
    loaded = load_run(mock[0]["run_id"])
    results.append(check("存档读写 roundtrip", loaded["mode"] == "run_current_only"
                         and loaded["judgment"]["verdict"] == "current_only_limited"))

    print("\n创新点1 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
