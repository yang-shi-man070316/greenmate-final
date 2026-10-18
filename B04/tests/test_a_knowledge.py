"""Test A：知识库中存在相关内容，LLM 回答应引用检索到的知识。

- 检索：问题「温度 36℃、湿度 35% 该怎么处理」+ 状态摘要 → 应命中 K04（高温应对）等；
- LLM：回答应引用知识（含 [依据知识: Kxx] 标注或片段关键内容），而非凭空回答；
- 对比：同一问题先带知识、再（模拟）无知识回答，输出应明显不同。

前置：.env 已配置真实 LLM_API_KEY（无需启动服务，直接调 B04 函数）。
运行：python B04/tests/test_a_knowledge.py
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

QUESTION = "当前温度 36℃，湿度 35%，该怎么处理？"


def main():
    state = STATES["B"]
    query = build_query(QUESTION, state)
    evidence = retrieve(query, top_k=3)
    print("检索 query: %s" % query)
    print("检索命中 %d 条: %s\n" % (len(evidence), [e["id"] + " " + e["topic"] for e in evidence]))

    if not evidence:
        print("[FAIL] 检索未命中，请检查知识库/检索逻辑")
        return 1

    result = ask_with_knowledge(QUESTION, state, evidence)
    if result["status"] == "error":
        print("[无法执行] LLM 调用失败：[%s] %s" % (result.get("error_type"), result.get("message")))
        print("请先在项目根目录 .env 配置真实 LLM_API_KEY 后重跑（Test A 需要真实 LLM）")
        return 1

    print("=== 带知识回答（%sms） ===\n%s\n" % (result["elapsed_ms"], result["answer"]))

    no_ev_result = ask_with_knowledge(QUESTION, state, [])
    print("=== 无知识回答（对比，%sms） ===\n%s\n" % (no_ev_result["elapsed_ms"], no_ev_result["answer"]))

    answer = result["answer"]
    checks = [
        ("检索命中知识片段", len(evidence) > 0),
        ("回答引用知识（含 K0x 或「依据知识」标注）",
         ("K0" in answer) or ("依据知识" in answer)),
        ("回答包含知识库关键内容（遮阴/通风/加湿 至少其一）",
         any(k in answer for k in ("遮阴", "通风", "加湿", "喷雾"))),
        ("带知识与无知识回答不同", answer != no_ev_result["answer"]),
    ]
    ok = True
    print("-" * 64)
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("-" * 64)
    print("Test A 结论：%s" % ("通过 ✅（LLM 回答引用检索知识，与无知识回答明显不同）" if ok else "未完全通过 ❌（对照上方回答人工复核）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
