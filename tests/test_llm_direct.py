"""步骤3：单独调通 LLM API（不经 FastAPI，验证密钥与连接，并打印完整上下文）。

前置：.env 已配置真实 LLM_API_KEY（服务运行中修改 .env 无需重启）。
运行（项目根目录）：python tests/test_llm_direct.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import ask_llm, build_messages  # noqa: E402
from states import STATES  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    state = STATES["A"]
    question = "当前环境怎么样？"

    print("发送给 LLM 的上下文（状态必须放进请求上下文）：")
    print("-" * 64)
    for m in build_messages(state, question):
        print("[%s]\n%s\n" % (m["role"], m["content"]))
    print("-" * 64)

    result = ask_llm(state=state, question=question)
    if result["status"] == "success":
        print("LLM 返回（%sms）：\n%s" % (result["elapsed_ms"], result["answer"]))
    else:
        print("LLM 调用失败：[%s] %s" % (result["error_type"], result["message"]))
        sys.exit(1)


if __name__ == "__main__":
    main()
