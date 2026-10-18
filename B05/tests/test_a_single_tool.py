"""TestA【单工具】：帮我查看当前环境状态 → 应调用 get_current_environment。

- Agent 自主决策调用工具（不写死顺序）；
- 断言：存在 get_current_environment 的真实调用（execution.real=True），
  tool_result.status=ok，最终回答引用环境数值。

前置：.env 已配置真实 LLM_API_KEY（复用 B01 配置）。
运行：python B05/tests/test_a_single_tool.py
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

TASK = "帮我查看当前环境状态"


def main():
    result = run_agent(TASK)
    if result["status"] == "error":
        print("[无法执行] %s" % result.get("message"))
        return 1

    print("=== 调用链路 ===")
    for s in result["steps"]:
        print("Round %d: tool_call %s(%s) → execute %sms → tool_result status=%s" % (
            s["iteration"], s["tool_call"]["name"],
            json.dumps(s["tool_call"]["arguments"], ensure_ascii=False),
            s["execution"].get("elapsed_ms"), s["tool_result"]["status"]))
    print("\n=== 最终回答 ===\n%s\n" % result["answer"])

    env_step = [s for s in result["steps"] if s["tool_call"]["name"] == "get_current_environment"]
    checks = [
        ("调用了 get_current_environment", len(env_step) >= 1),
        ("工具真实执行（execution.real）", bool(env_step) and env_step[0]["execution"].get("real")),
        ("tool_result status=ok", bool(env_step) and env_step[0]["tool_result"]["status"] == "ok"),
        ("最终回答非空", bool(result["answer"])),
        ("回答引用环境数值（含温度数值）",
         bool(env_step) and str(env_step[0]["tool_result"]["data"]["temperature"]) in result["answer"]),
    ]
    ok = True
    print("-" * 64)
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("-" * 64)
    print("TestA 结论：%s" % ("通过 ✅（单工具被 LLM 自主选中并真实执行，回答引用真实数据）" if ok else "未完全通过 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
