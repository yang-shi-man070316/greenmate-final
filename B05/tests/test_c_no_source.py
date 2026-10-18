"""No-source【失败边界】：负数 hours / 不存在地名 / 知识库无匹配。

- 工具必须如实返回 error / unavailable（不得伪装成功）；
- Agent 最终回答必须明确说明证据缺失/不可用，不编造内容；
- 三个用例分别独立执行（每轮全新 Agent 会话）。

前置：.env 已配置真实 LLM_API_KEY。
运行：python B05/tests/test_c_no_source.py
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

CASES = [
    {
        "name": "负数 hours（get_environment_history 应返回 error）",
        "task": "查询最近 -5 小时的环境历史",
        "expect_tool": "get_environment_history",
        "expect_status": "error",
        "answer_must": ("负数", "无效", "错误", "失败", "不能"),
    },
    {
        "name": "不存在地名（get_weather_evidence 应返回 error）",
        "task": "查一下不存在的地方 火星城市xyz 的天气",
        "expect_tool": "get_weather_evidence",
        "expect_status": "error",
        "answer_must": ("未找到", "不存在", "错误", "失败", "无法"),
    },
    {
        "name": "知识库无匹配（search_tomato_knowledge 应返回 unavailable）",
        "task": "检索知识库：火星土壤的 pH 值是多少",
        "expect_tool": "search_tomato_knowledge",
        "expect_status": "unavailable",
        "answer_must": ("未找到", "缺失", "没有", "不可用"),
    },
]


def main():
    ok = True
    for case in CASES:
        result = run_agent(case["task"])
        print("=" * 64)
        print("用例：%s" % case["name"])
        if result["status"] == "error":
            print("[无法执行] %s" % result.get("message"))
            ok = False
            continue
        for s in result["steps"]:
            print("Round %d: tool_call %s(%s) → tool_result status=%s" % (
                s["iteration"], s["tool_call"]["name"],
                json.dumps(s["tool_call"]["arguments"], ensure_ascii=False),
                s["tool_result"]["status"]))
        print("=== 最终回答 ===\n%s" % result["answer"])

        tool_steps = [s for s in result["steps"] if s["tool_call"]["name"] == case["expect_tool"]]
        answer = result["answer"]
        checks = [
            ("调用了 %s" % case["expect_tool"], len(tool_steps) >= 1),
            ("tool_result status=%s" % case["expect_status"],
             bool(tool_steps) and tool_steps[-1]["tool_result"]["status"] == case["expect_status"]),
            ("回答明确说明证据缺失/失败（不编造）",
             bool(answer) and any(k in answer for k in case["answer_must"])),
        ]
        for name, passed in checks:
            print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
            ok = ok and passed
        print()
    print("=" * 64)
    print("No-source 结论：%s" % ("通过 ✅（失败边界全部如实报错，Agent 明确说明证据缺失、未编造）" if ok else "存在未通过项 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
