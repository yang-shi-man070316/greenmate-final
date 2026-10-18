"""Test B：知识库中没有相关内容，LLM 必须说明「未找到相关知识」，不编造。

- 问题「火星土壤的 pH 值是多少？」不在本地知识库范围 → 检索为空；
- LLM 被强制（system prompt）首先说明「未找到相关知识」，禁止编造知识性结论；
- 断言：回答含「未找到」；不出现知识引用标注（[依据知识）；无知识证据。

前置：.env 已配置真实 LLM_API_KEY。
运行：python B04/tests/test_b_no_knowledge.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B04 目录
sys.path.insert(0, str(ROOT))

from b04_llm import ask_with_knowledge  # noqa: E402
from retriever import build_query, retrieve  # noqa: E402
from states import STATES  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

QUESTION = "火星土壤的 pH 值是多少？"


def main():
    state = STATES["A"]
    query = build_query(QUESTION, state)
    evidence = retrieve(query, top_k=3)
    print("检索 query: %s" % query)
    print("检索命中 %d 条（应为 0）\n" % len(evidence))

    if evidence:
        print("[FAIL] 预期检索为空，实际命中 %s" % [e["id"] for e in evidence])
        return 1

    result = ask_with_knowledge(QUESTION, state, evidence)
    if result["status"] == "error":
        print("[无法执行] LLM 调用失败：[%s] %s" % (result.get("error_type"), result.get("message")))
        print("请先在项目根目录 .env 配置真实 LLM_API_KEY 后重跑（Test B 需要真实 LLM）")
        return 1

    answer = result["answer"]
    print("=== LLM 回答（无知识，%sms） ===\n%s\n" % (result["elapsed_ms"], answer))

    checks = [
        ("检索结果为空", len(evidence) == 0),
        ("回答明确说明「未找到相关知识」", "未找到" in answer),
        ("不出现知识引用标注（未伪造引用）", "依据知识" not in answer and "[依据知识" not in answer),
        ("不编造具体知识性数值（不出现 pH 数值结论）", "pH" not in answer.replace("pH 值是多少", "")),
    ]
    ok = True
    print("-" * 64)
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("-" * 64)
    print("Test B 结论：%s" % ("通过 ✅（无知识时明确说明未找到，未编造）" if ok else "未完全通过 ❌（对照上方回答人工复核）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
