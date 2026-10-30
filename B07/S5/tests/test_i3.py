"""创新点3 测试（无需 LLM Key / 无需联网）。

- 天气方向判定：升温桩 → warming；降温桩 → cooling；
- 三组判定：agree→attention_confirmed / conflict→attention_uncertain /
  missing_weather→attention_weather_missing；
- LLM prompt：两块式 + 禁止词 + 禁止脑补约束；
- 自检：强确定词检出、missing 场景脑补检出、两块式；
- run_id/存档。

运行：python B07/S5/tests/test_i3.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
S5 = Path(__file__).resolve().parent.parent  # B07/S5
for d in (ROOT / "B07" / "S4", ROOT / "B06", ROOT / "B05", ROOT / "B04",
          ROOT / "B03", ROOT / "B02", ROOT, S5):
    sys.path.insert(0, str(d))

from B07.S4.llm_explain import check_forbidden  # noqa: E402

from i3_check import check_weather_fabrication  # noqa: E402
from i3_judgment import build_judgment, weather_direction  # noqa: E402
from i3_llm import SYSTEM_PROMPT, build_messages  # noqa: E402
from i3_run import load_run, make_run_id, save_run  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def _weather_ev(temps):
    hourly = [{"time": "2026-10-31T%02d:00" % h, "temperature_2m": t}
              for h, t in enumerate(temps, start=1)]
    return {"status": "ok", "source_type": "external_weather",
            "data": {"forecast": {"hourly": hourly}}}


def main():
    results = []

    # 1. 天气方向判定
    results.append(check("升温桩 → warming", weather_direction(_weather_ev([30.5, 31.5, 32.0])) == "warming"))
    results.append(check("降温桩 → cooling", weather_direction(_weather_ev([30.0, 28.5, 27.0])) == "cooling"))
    results.append(check("平稳 → neutral", weather_direction(_weather_ev([30.0, 30.2, 29.9])) == "neutral"))

    # 2. 三组判定
    e1 = {"evidence_id": "E1", "source_type": "internal_history", "status": "ok",
          "source": "greenmate_b02_db", "time": "t", "result": {"trend": "升温"}}
    e2 = {"evidence_id": "E2", "source_type": "ml_prediction", "status": "ok",
          "source": "greenmate_b06_rf", "time": "t", "result": {"predicted_attention": "WATCH"}}
    e4 = {"evidence_id": "E4", "source_type": "local_knowledge", "status": "ok",
          "source": "greenmate_b04_kb", "time": "t", "result": {"segments": [{"id": "K09"}]}}
    e3w = _weather_ev([30.5, 31.5, 32.0]); e3w["evidence_id"] = "E3"
    e3c = _weather_ev([30.0, 28.5, 27.0]); e3c["evidence_id"] = "E3"
    m3 = {"evidence_id": "E3", "source_type": "external_weather", "status": "error",
          "source": "weather_api", "time": "t", "result": None,
          "error": {"error_type": "network_error", "message": "无法连接天气 API"}}

    j_agree = build_judgment("run_agree", [e1, e2, e3w, e4], [], e3w)
    results.append(check("run_agree → attention_confirmed（证据一致，结论相对明确）",
                         j_agree["verdict"] == "attention_confirmed"
                         and "一致" in j_agree["verdict_note"], j_agree["verdict"]))
    j_conflict = build_judgment("run_conflict", [e1, e2, e3c, e4], [], e3c)
    results.append(check("run_conflict → attention_uncertain（保留分歧，不判定胜负）",
                         j_conflict["verdict"] == "attention_uncertain"
                         and "不判定证据胜负" in j_conflict["verdict_note"], j_conflict["verdict"]))
    j_missing = build_judgment("run_missing_weather", [e1, e2, e4], [m3])
    results.append(check("run_missing_weather → attention_weather_missing（收缩边界）",
                         j_missing["verdict"] == "attention_weather_missing"
                         and "禁止脑补" in j_missing["verdict_note"], j_missing["verdict"]))
    results.append(check("三组 verdict 互不相同（推理边界随证据条件变化）",
                         len({j_agree["verdict"], j_conflict["verdict"],
                              j_missing["verdict"]}) == 3))

    # 3. LLM 约束
    results.append(check("prompt 含两块式 + 禁止词 + 禁止脑补",
                         "可判断内容" in SYSTEM_PROMPT and "受限说明" in SYSTEM_PROMPT
                         and "一定" in SYSTEM_PROMPT and "必然" in SYSTEM_PROMPT
                         and "脑补" in SYSTEM_PROMPT))
    msgs = build_messages("固定提问", [e1, e2], [m3], j_missing)
    results.append(check("missing 场景 LLM 上下文含缺失清单与表达强度要求",
                         "缺失证据清单" in msgs[1]["content"]
                         and "表达强度" in msgs[1]["content"]))

    # 4. 自检逻辑
    results.append(check("禁止词校验（含否定语境与程度副词排除）",
                         check_forbidden("温度必然继续升高") == ["必然"]
                         and check_forbidden("不能证明一定继续恶化") == []
                         and check_forbidden("外部条件对高温有一定延续性") == []))
    rec_missing = {"mode": "run_missing_weather",
                   "llm_explanation": {"answer": "【可判断内容】温度偏高\n【受限说明】天气数据缺失，无法判断降水"}}
    ok_fab, hits = check_weather_fabrication(rec_missing)
    results.append(check("missing 场景脑补检出（出现「降水」→ 疑似私自补齐）",
                         not ok_fab and "降水概率" not in hits and hits, str(hits)))
    rec_clean = {"mode": "run_missing_weather",
                 "llm_explanation": {"answer": "【可判断内容】基于历史与模型…\n【受限说明】天气证据缺失，相关判断不可靠"}}
    ok_fab2, _ = check_weather_fabrication(rec_clean)
    results.append(check("missing 场景未脑补时通过", ok_fab2))

    # 5. run_id 与存档
    rid = make_run_id()
    results.append(check("run_id 为 i3- 前缀", bool(re.match(r"^i3-\d{14}-[0-9a-f]{6}$", rid)), rid))
    record = {"run_id": rid, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "mode": "run_agree", "experiment": "innovate3",
              "adopted_evidence": [e1, e2, e3w, e4], "missing_evidence": [],
              "judgment": j_agree,
              "llm_explanation": {"status": "error", "error_type": "test", "message": "无 LLM"}}
    path = save_run(record)
    loaded = load_run(rid)
    results.append(check("存档读写 roundtrip", loaded["run_id"] == rid
                         and loaded["judgment"]["verdict"] == "attention_confirmed", str(path)))

    print("\n创新点3 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
