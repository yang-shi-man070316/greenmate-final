"""TestB【多工具】：查 24h 环境历史 + 南京天气 + 高温低湿养护建议 → LLM 自主选择多个工具。

- 任务需要三类数据（历史/天气/知识），工具调用顺序由 LLM 决定，禁止写死；
- 断言：至少调用 2 个不同工具且全部真实执行（execution.real=True）、
  调用集合包含 get_environment_history 与 get_weather_evidence、
  tool_result 无 execution_error，最终回答非空。

前置：.env 已配置真实 LLM_API_KEY。
运行：python B05/tests/test_b_multi_tool.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B05 目录
sys.path.insert(0, str(ROOT))

from agent import run_agent  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

TASK = "帮我查最近24小时的环境历史、南京的天气，再给出高温低湿环境下的养护建议"


def main():
    result = run_agent(TASK)
    if result["status"] == "error":
        print("[无法执行] %s" % result.get("message"))
        return 1

    print("=== 调用链路（共 %d 次工具调用，%d 轮） ===" % (len(result["steps"]), result["iterations"]))
    for s in result["steps"]:
        print("Round %d: tool_call %s(%s) → execute %sms → tool_result status=%s" % (
            s["iteration"], s["tool_call"]["name"],
            json.dumps(s["tool_call"]["arguments"], ensure_ascii=False),
            s["execution"].get("elapsed_ms"), s["tool_result"]["status"]))
    print("\n=== 最终回答 ===\n%s\n" % result["answer"])

    names = [s["tool_call"]["name"] for s in result["steps"]]
    checks = [
        ("至少调用 2 个不同工具", len(set(names)) >= 2),
        ("调用了 get_environment_history", "get_environment_history" in names),
        ("调用了 get_weather_evidence", "get_weather_evidence" in names),
        ("全部工具真实执行", all(s["execution"].get("real") for s in result["steps"])),
        ("无执行异常", all(s["tool_result"]["status"] != "error" or
                       s["tool_result"].get("error", {}).get("error_type") != "execution_error"
                       for s in result["steps"])),
        ("最终回答非空", bool(result["answer"])),
    ]
    ok = True
    print("-" * 64)
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("-" * 64)
    print("TestB 结论：%s" % ("通过 ✅（LLM 自主选择多工具并真实执行，回答基于多来源证据）" if ok else "未完全通过 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
