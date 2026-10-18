"""失败验证（无需 LLM Key / 无需联网）：检索为空时系统不能强行补全结论。

用例：
1. 检索为空 + LLM 未配置 → 返回 config_error，响应中没有任何编造的答案内容；
2. 检索为空（正常检索路径）→ evidence 为空，检索层绝不生成伪证据；
3. 空问题 → app 层校验拒绝（400）。

运行：python B04/tests/test_failures.py
"""

import os
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


def main():
    results = []
    state = STATES["A"]

    # 用例 1：检索为空 + 无 LLM Key → 明确报错，绝不编造
    saved_key = os.environ.get("LLM_API_KEY")
    os.environ["LLM_API_KEY"] = ""
    try:
        question = "火星土壤的 pH 值是多少？"
        evidence = retrieve(build_query(question, state), top_k=3)
        result = ask_with_knowledge(question, state, evidence)
        passed = (len(evidence) == 0
                  and result["status"] == "error"
                  and result.get("error_type") == "config_error"
                  and "answer" not in result)
        results.append(passed)
        print("用例：检索为空 + LLM 未配置（不能强行补全结论）")
        print("  检索命中: %d 条 | 返回 status: %s | error_type: %s" % (
            len(evidence), result.get("status"), result.get("error_type")))
        print("  响应中无编造的答案内容: %s" % ("answer" not in result))
        print("  结论: %s\n" % ("PASS ✅" if passed else "FAIL ❌"))
    finally:
        if saved_key is None:
            os.environ.pop("LLM_API_KEY", None)
        else:
            os.environ["LLM_API_KEY"] = saved_key

    # 用例 2：库外问题检索为空（检索层不生成伪证据）
    evidence = retrieve("量子纠缠与植物光合作用的关系", top_k=3)
    passed = len(evidence) == 0
    results.append(passed)
    print("用例：库外问题检索为空（检索层不生成伪证据）")
    print("  检索命中: %d 条（应为 0）" % len(evidence))
    print("  结论: %s\n" % ("PASS ✅" if passed else "FAIL ❌"))

    # 用例 3：空问题校验（app 层拒绝）
    try:
        from app import ChatRequest, chat
        try:
            chat(ChatRequest(question="   "))
            passed = False
            detail = "未拒绝空问题"
        except Exception as e:
            passed = getattr(e, "status_code", None) == 400
            detail = str(getattr(e, "detail", e))
        results.append(passed)
        print("用例：空问题校验（app 层拒绝）")
        print("  %s" % detail)
        print("  结论: %s\n" % ("PASS ✅" if passed else "FAIL ❌"))
    except ImportError as e:
        print("用例：空问题校验 —— 跳过（%s）\n" % e)

    print("失败验证总结论：%s" % ("全部通过 ✅（检索为空时不补全、不编造、明确报错）" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
