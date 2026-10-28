"""S5 证据退化实验测试（无需 LLM Key / 无需联网）。

- 三种单一故障注入：证据状态正确、同一时间只有一种故障；
- 退化判定：verdict 随缺失证据类型变化，缺失清单与原因可追溯；
- LLM 两块式约束（prompt 校验）；
- run_id s5- 格式 + 存档读写；报告生成（mock 对比）。

运行：python B07/S5/tests/test_s5.py
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

from s5_judgment import build_judgment, is_missing  # noqa: E402
from s5_llm_explain import SYSTEM_PROMPT, build_messages  # noqa: E402
from run import collect_evidence, load_run, make_run_id, save_run  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def main():
    results = []

    # 1. 三种故障注入（同一时间只触发一种）
    for fault, expect_missing_type, expect_status in (
            ("weather_unavailable", "external_weather", "error"),
            ("rag_insufficient", "local_knowledge", "ok"),
            ("tool_error", "external_weather", "error")):
        adopted, missing = collect_evidence(fault, [])
        results.append(check("故障 %s：恰好 1 条缺失证据（%s）" % (fault, expect_missing_type),
                             len(missing) == 1
                             and missing[0]["source_type"] == expect_missing_type
                             and missing[0]["status"] == expect_status
                             and len(adopted) == 3,
                             "adopted=%d missing=%d" % (len(adopted), len(missing))))
        results.append(check("故障 %s：其余证据全部有效（status=ok）" % fault,
                             all(ev["status"] == "ok" for ev in adopted)))
    rag_missing = collect_evidence("rag_insufficient", [])[1][0]
    results.append(check("rag_insufficient：no_match 标记存在",
                         bool((rag_missing.get("result") or {}).get("no_match"))))

    # 2. 退化判定
    from B07.S4 import evidence as ev_mod
    e1 = ev_mod.wrap("internal_history", "greenmate_b02_db", "ok", result={"trend": "升温"})
    e2 = ev_mod.wrap("ml_prediction", "greenmate_b06_rf", "ok",
                     result={"predicted_attention": "WATCH"}, model_version="b06-rf-v1")
    e3 = ev_mod.wrap("external_weather", "open_meteo", "ok",
                     result={"forecast": {"hourly": []}}, provider="open_meteo",
                     forecast_time=["2026-10-27T20:00"])
    e4 = ev_mod.wrap("local_knowledge", "greenmate_b04_kb", "ok",
                     result={"segments": [{"id": "K09"}]}, citation=[{"id": "K09"}])

    j0 = build_judgment([e1, e2, e3, e4], [])
    results.append(check("基线（无缺失）→ attention_uncertain，degraded=False",
                         j0["verdict"] == "attention_uncertain" and not j0["degraded"],
                         j0["verdict"]))
    m3 = dict(e3, status="error",
              error={"error_type": "network_error", "message": "无法连接天气 API"})
    j1 = build_judgment([e1, e2, e4], [m3])
    results.append(check("天气缺失 → attention_weather_missing + 缺失清单可追溯",
                         j1["verdict"] == "attention_weather_missing"
                         and j1["missing_evidence"][0]["source_type"] == "external_weather"
                         and "无法连接天气 API" in j1["missing_evidence"][0]["reason"],
                         j1["verdict"]))
    m4 = dict(e4, result={"no_match": True})
    j2 = build_judgment([e1, e2, e3], [m4])
    results.append(check("知识缺失 → attention_knowledge_missing（检索不足归因）",
                         j2["verdict"] == "attention_knowledge_missing"
                         and "检索无匹配" in j2["missing_evidence"][0]["reason"],
                         j2["verdict"]))
    j3 = build_judgment([e3, e4], [dict(e1, status="error"), dict(e2, status="error")])
    results.append(check("内部证据缺失 → inconclusive_degraded",
                         j3["verdict"] == "inconclusive_degraded", j3["verdict"]))
    results.append(check("is_missing：error 与 no_match 均判定缺失，ok 正常",
                         is_missing(m3) and is_missing(m4) and not is_missing(e1)))

    # 3. LLM 两块式约束
    results.append(check("prompt 强制两块（可判断内容 + 受限说明）且禁止『无法分析』",
                         "可判断内容" in SYSTEM_PROMPT and "受限说明" in SYSTEM_PROMPT
                         and "禁止直接回复『无法分析』" in SYSTEM_PROMPT
                         and "禁止编造" in SYSTEM_PROMPT))
    msgs = build_messages("固定提问", [e1, e2], [m3], j1)
    results.append(check("LLM 上下文含有效/缺失清单与判定",
                         "有效证据清单" in msgs[1]["content"]
                         and "缺失证据清单" in msgs[1]["content"]
                         and "无法连接天气 API" in msgs[1]["content"]))

    # 4. run_id 与存档
    rid = make_run_id()
    results.append(check("run_id 为 s5- 前缀", bool(re.match(r"^s5-\d{14}-[0-9a-f]{6}$", rid)), rid))
    record = {"run_id": rid, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "mode": "fault", "fault": "weather_unavailable", "experiment": "S5_fault",
              "adopted_evidence": [e1, e2, e4], "missing_evidence": [m3],
              "structured_judgment": j1,
              "llm_explanation": {"status": "error", "error_type": "test", "message": "无 LLM"}}
    path = save_run(record)
    loaded = load_run(rid)
    results.append(check("存档读写 roundtrip", loaded["run_id"] == rid
                         and loaded["structured_judgment"]["verdict"] == "attention_weather_missing",
                         str(path)))

    print("\nS5 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
