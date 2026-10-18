"""4 个标准工具单独调试（脱离 LLM，无需密钥）：人工校验返回结果。

运行：python B05/tests/test_tools.py
校验点：
- 统一返回结构：status / source / provider / retrieved_at（+data 或 error）；
- status 仅 ok / unavailable / error；
- 负数 hours → error；无效地点 → error；知识库无匹配 → unavailable；
- get_weather_evidence 成功用例需要联网。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B05 目录
sys.path.insert(0, str(ROOT))

from tools import (  # noqa: E402
    get_current_environment, get_environment_history,
    get_weather_evidence, search_tomato_knowledge,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

ALLOWED = ("ok", "unavailable", "error")


def check_structure(name, r):
    keys_ok = all(k in r for k in ("status", "source", "provider", "retrieved_at"))
    status_ok = r.get("status") in ALLOWED
    body_ok = ("data" in r) ^ ("error" in r)  # data 与 error 二选一
    print("工具：%s" % name)
    print("  status=%s | source=%s | provider=%s | retrieved_at=%s" % (
        r.get("status"), r.get("source"), r.get("provider"), r.get("retrieved_at")))
    if r.get("data") is not None:
        d = r["data"]
        if "samples" in d:
            print("  data: %s 条样本，窗口 %s ~ %s，温度 %.1f~%.1f℃" % (
                d["count"], d["window_start"], d["window_end"],
                d["stats"]["fields"]["temperature"]["min"], d["stats"]["fields"]["temperature"]["max"]))
        elif "segments" in d:
            print("  data: %d 个知识片段：%s" % (d["count"], [s["id"] for s in d["segments"]]))
        elif "weather" in d:
            print("  data: %s 天气 %.1f℃ / %s" % (d["resolved"]["name"],
                  d["weather"]["temperature_c"], d["weather"]["weather_text"]))
        else:
            print("  data: %s" % r["data"])
    if r.get("error") is not None:
        print("  error: [%s] %s" % (r["error"].get("error_type"), r["error"].get("message")))
    passed = keys_ok and status_ok and body_ok
    print("  结论: %s\n" % ("PASS ✅" if passed else "FAIL ❌"))
    return passed


def main():
    cases = [
        ("get_current_environment（无参数，应为 ok）",
         get_current_environment(), "ok"),
        ("get_environment_history(24)（应为 ok，有样本）",
         get_environment_history(24), "ok"),
        ("get_environment_history(-5)（负数，应为 error）",
         get_environment_history(-5), "error"),
        ("get_weather_evidence(北京)（真实联网，应为 ok）",
         get_weather_evidence("北京"), "ok"),
        ("get_weather_evidence(火星城市xyz)（无效地点，应为 error）",
         get_weather_evidence("火星城市xyz"), "error"),
        ("search_tomato_knowledge(高温 干燥 养护)（应为 ok，带引用）",
         search_tomato_knowledge("高温 干燥 养护"), "ok"),
        ("search_tomato_knowledge(火星土壤的pH值)（无匹配，应为 unavailable）",
         search_tomato_knowledge("火星土壤的pH值"), "unavailable"),
    ]
    ok = True
    for name, r, expect in cases:
        passed = check_structure(name, r)
        if r.get("status") != expect:
            print("  [FAIL] 期望 status=%s，实际 %s\n" % (expect, r.get("status")))
            passed = False
        ok = ok and passed
    print("工具单独调试总结论：%s" % ("全部通过 ✅（4 个工具脱离 LLM 可独立运行，返回结构统一）" if ok else "存在未通过项 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
