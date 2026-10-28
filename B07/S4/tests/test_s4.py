"""S4 测试（无需 LLM Key / 无需联网）：
- 证据统一字段与 status 取值（ok/unavailable/error）；
- B05 工具层 unavailable(no_match) → 证据层 ok 的语义映射；
- 分歧判定三部分合成 + 证据绑定 + 反向查询；
- 幻觉约束（禁止词校验 + prompt 含三部分/禁止词）；
- 降温场景桩 + B03 fetch_forecast（temperature_2m、forecast_time 校验）；
- B04 检索命中 K09；B06 对固定升温段真实输出 WATCH；
- run_id s4- 格式 + 存档读写。

运行：python B07/S4/tests/test_s4.py
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
S4 = Path(__file__).resolve().parent.parent  # B07/S4
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT, S4):
    sys.path.insert(0, str(d))

from B03 import weather_client  # noqa: E402
from B05.tools import get_weather_forecast, search_tomato_knowledge  # noqa: E402

import evidence  # noqa: E402
from judgment import build_judgment, explain_conclusion  # noqa: E402
from llm_explain import FORBIDDEN_WORDS, SYSTEM_PROMPT, build_messages, check_forbidden  # noqa: E402
from run import load_internal_evidence, load_run, make_run_id, save_run  # noqa: E402
from weather_stub import CoolingStub  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def main():
    results = []

    # 1. 证据统一字段与 status 取值
    ev = evidence.wrap("internal_history", "greenmate_b02_db", "ok",
                       result={"a": 1}, model_version="b06-rf-v1")
    results.append(check("证据基础字段齐全（source_type/source/time/status/result/error）",
                         all(k in ev for k in ("source_type", "source", "time",
                                               "status", "result", "error"))
                         and ev["status"] == "ok"))
    try:
        evidence.wrap("x", "y", "bogus")
        results.append(check("非法 status 被拒绝", False, "未抛异常"))
    except ValueError:
        results.append(check("非法 status 被拒绝", True))

    # 2. 工具层 → 证据层语义映射
    tool_no_match = {"status": "unavailable", "source": "local_knowledge",
                     "error": {"error_type": "no_match", "message": "无匹配"}}
    ev2 = evidence.from_tool("local_knowledge", "greenmate_b04_kb", tool_no_match)
    results.append(check("RAG 无匹配（工具层 unavailable）→ 证据层 ok", ev2["status"] == "ok"
                         and ev2["result"].get("no_match") is True))
    tool_err = {"status": "error", "source": "external_api",
                "error": {"error_type": "not_found", "message": "未找到"}}
    ev3 = evidence.from_tool("external_weather", "open_meteo", tool_err)
    results.append(check("工具层 error → 证据层 error", ev3["status"] == "error"))

    # 3. 分歧判定
    e1 = evidence.wrap("internal_history", "greenmate_b02_db", "ok",
                       result={"trend": "持续升温"})
    e2 = evidence.wrap("ml_prediction", "greenmate_b06_rf", "ok",
                       result={"predicted_attention": "WATCH"}, model_version="b06-rf-v1")
    j_base = build_judgment([e1, e2])
    results.append(check("baseline（E1+E2）→ verdict=attention", j_base["verdict"] == "attention",
                         j_base["verdict"]))
    e3 = evidence.wrap("external_weather", "open_meteo", "ok",
                       result={"forecast": {"hourly": [{"temperature_2m": 28}]}},
                       provider="open_meteo", forecast_time=["2026-10-22T20:00"])
    e4 = evidence.wrap("local_knowledge", "greenmate_b04_kb", "ok",
                       result={"segments": [{"id": "K09"}]}, citation=[{"id": "K09"}])
    j_full = build_judgment([e1, e2, e3, e4])
    results.append(check("with_evidence（E1~E4）→ verdict=attention_uncertain",
                         j_full["verdict"] == "attention_uncertain", j_full["verdict"]))
    results.append(check("三部分合成：支持=2 缓解=1 不确定=1",
                         len(j_full["synthesis"]["support_attention"]) == 2
                         and len(j_full["synthesis"]["mitigating_or_reverse"]) == 1
                         and len(j_full["synthesis"]["insufficient"]) == 1))
    results.append(check("反向查询：E3 结论依据可回溯",
                         "E3" in explain_conclusion(j_full, "E3")
                         and "external_weather" in explain_conclusion(j_full, "E3")))

    # 4. 幻觉约束
    results.append(check("禁止词校验：命中『一定/必然/肯定』",
                         check_forbidden("温度必然继续升高") == ["必然"]
                         and check_forbidden("这一定是风险") == ["一定"]
                         and check_forbidden("情况稳定") == []))
    results.append(check("禁止词校验：否定语境不算命中（如引用知识原文）",
                         check_forbidden("历史趋势不能证明未来一定继续恶化") == []
                         and check_forbidden("无法肯定后续变化") == []))
    results.append(check("prompt 含三部分输出与禁止词约束",
                         "支持提高关注的证据" in SYSTEM_PROMPT
                         and "可能缓解" in SYSTEM_PROMPT
                         and "不足以确定" in SYSTEM_PROMPT
                         and all(w in SYSTEM_PROMPT for w in FORBIDDEN_WORDS)))
    messages = build_messages([e1, e2], j_base)
    results.append(check("LLM 上下文含证据编号绑定（[E1] [E2]）",
                         "[E1]" in messages[1]["content"] and "[E2]" in messages[1]["content"]))

    # 5. 降温桩 + B03 fetch_forecast
    stub = CoolingStub()
    stub.start()
    saved = os.environ.get("WEATHER_BASE_URL")
    os.environ["WEATHER_BASE_URL"] = stub.base_url
    try:
        fc = weather_client.fetch_forecast("32.06,118.79", hours=6)
    finally:
        if saved is None:
            os.environ.pop("WEATHER_BASE_URL", None)
        else:
            os.environ["WEATHER_BASE_URL"] = saved
        stub.stop()
    results.append(check("B03 预报含 temperature_2m（降温场景）",
                         fc["status"] == "success"
                         and all("temperature_2m" in h for h in fc["forecast"]["hourly"])
                         and fc["forecast"]["hourly"][0]["temperature_2m"]
                         > fc["forecast"]["hourly"][2]["temperature_2m"],
                         [h["temperature_2m"] for h in fc["forecast"]["hourly"][:3]]))
    results.append(check("forecast_time 晚于 retrieved_at",
                         all(ts.replace("T", " ") > fc["retrieved_at"]
                             for ts in fc["forecast_time"][:1])))

    # 6. B04 检索命中 K09
    k = search_tomato_knowledge("持续高温 未来 恶化 趋势")
    results.append(check("B05 知识检索命中 K09（趋势判断限制）",
                         any(s["id"] == "K09" for s in (k.get("data") or {}).get("segments", []))))

    # 7. B06 对固定升温段真实输出 WATCH
    log = []
    e1r, e2r = load_internal_evidence(log)
    results.append(check("B06 对 10-08 升温段真实输出 WATCH（不修改）",
                         e2r["result"]["predicted_attention"] == "WATCH",
                         "概率=%s" % e2r["result"]["probability"]))
    results.append(check("B02 升温段：26.3→38.1℃ 持续升温",
                         e1r["result"]["temperature_first"] < 27
                         and e1r["result"]["temperature_last"] > 37))

    # 8. run_id 与存档
    rid = make_run_id()
    results.append(check("run_id 为 s4- 前缀", bool(re.match(r"^s4-\d{14}-[0-9a-f]{6}$", rid)), rid))
    record = {"run_id": rid, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "mode": "baseline", "experiment": "S4_baseline", "evidence": [e1r, e2r],
              "pipeline_log": log, "structured_judgment": j_base,
              "llm_explanation": {"status": "error", "error_type": "test", "message": "无 LLM"}}
    path = save_run(record)
    loaded = load_run(rid)
    results.append(check("存档读写 roundtrip", loaded["run_id"] == rid
                         and loaded["structured_judgment"]["verdict"] == "attention",
                         str(path)))

    print("\nS4 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
