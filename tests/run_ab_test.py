"""步骤4：A/B 验收测试（端到端，走 HTTP，与页面同一条链路）。

前置条件：
1. 服务已启动：python main.py（项目根目录）
2. .env 已配置真实 LLM_API_KEY

验收标准：同一问题「当前环境怎么样？」，仅切换环境状态，
LLM 输出应随之变化，并引用对应数值（StateA: 24/65/12000，StateB: 36/35/22000）。

运行（项目根目录）：python tests/run_ab_test.py
记录自动写入 docs/AB_TEST_LAST_RUN.md
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402  （openai 的依赖，无需额外安装）

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
QUESTION = "当前环境怎么样？"


def main():
    client = httpx.Client(base_url=BASE, timeout=90)
    results = []

    for state_id in ("A", "B"):
        r = client.post("/api/state/switch", json={"state_id": state_id})
        r.raise_for_status()
        state = r.json()
        print("=== 切换到 %s：%s%s / %s%s / %s%s ===" % (
            state["label"], state["temperature"], state["temperature_unit"],
            state["humidity"], state["humidity_unit"], state["light"], state["light_unit"],
        ))

        r = client.post("/api/chat", json={"question": QUESTION})
        data = r.json()
        if r.status_code != 200:
            print("  [失败] HTTP %s：%s" % (r.status_code, data.get("message")))
            print("  提示：config_error 说明未配置密钥；auth_error 说明密钥无效，请检查 .env")
            sys.exit(1)
        print("  AI 回答（%sms）：%s" % (data["elapsed_ms"], data["answer"]))
        print()
        results.append({
            "state_id": state_id,
            "state": state,
            "answer": data["answer"],
            "messages_sent": data["messages_sent"],
            "elapsed_ms": data["elapsed_ms"],
        })

    a, b = results
    checks = [
        ("回答随状态变化（A ≠ B）", a["answer"] != b["answer"]),
        ("StateA 回答引用温度 24", "24" in a["answer"]),
        ("StateA 回答引用湿度 65", "65" in a["answer"]),
        ("StateA 回答引用光照 12000", "12000" in a["answer"]),
        ("StateB 回答引用温度 36", "36" in b["answer"]),
        ("StateB 回答引用湿度 35", "35" in b["answer"]),
        ("StateB 回答引用光照 22000", "22000" in b["answer"]),
    ]
    ok = True
    print("=" * 64)
    print("A/B 对比检查（同一问题，仅切换状态）")
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("=" * 64)
    if ok:
        print("验收结论：通过 ✅ 同一问题、仅切换环境状态，LLM 输出随状态变化并引用数值")
    else:
        print("验收结论：未完全通过 ❌（FAIL 项可能因措辞不同导致，请对照上方回答人工复核）")

    record_path = ROOT / "docs" / "AB_TEST_LAST_RUN.md"
    record_path.write_text(build_record(a, b, checks, ok), encoding="utf-8")
    print("本次记录已写入：docs/AB_TEST_LAST_RUN.md")
    return 0 if ok else 1


def build_record(a, b, checks, ok):
    lines = [
        "# A/B 测试记录（自动生成）",
        "",
        "- 时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "- 问题：%s" % QUESTION,
        "- 结论：%s" % ("通过 ✅" if ok else "未完全通过 ❌"),
        "",
    ]
    for r in (a, b):
        lines += [
            "## %s" % r["state"]["label"],
            "",
            "- 环境状态：温度 %s%s，湿度 %s%s，光照 %s%s，source_type=%s" % (
                r["state"]["temperature"], r["state"]["temperature_unit"],
                r["state"]["humidity"], r["state"]["humidity_unit"],
                r["state"]["light"], r["state"]["light_unit"],
                r["state"]["source_type"],
            ),
            "- AI 回答（%sms）：" % r["elapsed_ms"],
            "",
            "  %s" % r["answer"],
            "",
        ]
    lines += ["## 检查项", ""]
    for name, passed in checks:
        lines.append("- [%s] %s" % ("x" if passed else " ", name))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
