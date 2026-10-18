"""检索层单元测试（无需 LLM Key / 无需联网）。

验证最小检索逻辑：
- 有相关知识时返回 Top-K 且排序合理、证据可追溯（source/retrieved_at/scope/content）；
- 没有相关知识时返回空列表（系统不编造）。

运行：python B04/tests/test_retrieval.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B04 目录

from retriever import build_query, load_segments, retrieve  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

CASES = [
    {
        "name": "高温干燥处理（应命中 K04 高温应对）",
        "query": "当前温度 36 度、湿度 35%，该怎么处理？",
        "expect_hit": ["K04"],
        "expect_empty": False,
    },
    {
        "name": "强光灼伤（应命中 K06）",
        "query": "光照 22000 lux 会不会灼伤叶片？",
        "expect_hit": ["K06"],
        "expect_empty": False,
    },
    {
        "name": "SIMULATED 数据源（应命中 K07）",
        "query": "SIMULATED 数据源是什么？",
        "expect_hit": ["K07"],
        "expect_empty": False,
    },
    {
        "name": "库外问题（火星土壤 pH，应返回空）",
        "query": "火星土壤的 pH 值是多少？",
        "expect_hit": [],
        "expect_empty": True,
    },
    {
        "name": "库外问题 + 状态（门控：不注入状态数值，应仍为空）",
        "query": build_query("火星土壤的 pH 值是多少？", {
            "temperature": 24.0, "humidity": 65.0, "light": 12000.0}),
        "expect_hit": [],
        "expect_empty": True,
    },
    {
        "name": "状态摘要参与检索（StateB 36/35/22000 + 泛问题）",
        "query": build_query("当前环境怎么样？", {
            "temperature": 36.0, "humidity": 35.0, "light": 22000.0}),
        "expect_hit": ["K04"],
        "expect_empty": False,
    },
]


def main():
    print("知识库共 %d 个片段\n" % len(load_segments()))
    ok = True
    for case in CASES:
        evidence = retrieve(case["query"], top_k=3)
        ids = [e["id"] for e in evidence]
        passed_empty = (len(evidence) == 0) == case["expect_empty"]
        passed_hit = all(x in ids for x in case["expect_hit"])
        passed = passed_empty and passed_hit
        ok = ok and passed
        print("用例：%s" % case["name"])
        print("  query: %s" % case["query"])
        print("  命中: %s（期望含 %s）" % (ids or "空", case["expect_hit"] or "空"))
        for e in evidence:
            print("    [%s] %s | score=%s | source=%s | retrieved_at=%s | scope=%s"
                  % (e["id"], e["topic"], e["score"], e["source"], e["retrieved_at"], e["scope"]))
        print("  结论: %s\n" % ("PASS ✅" if passed else "FAIL ❌"))
    print("检索层测试总结论：%s" % ("全部通过 ✅" if ok else "存在未通过项 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
