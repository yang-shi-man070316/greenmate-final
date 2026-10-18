"""步骤5：失败测试——错误密钥 / 网络异常 / 缺失密钥，必须明确报错，不伪装成功。

直接调用 llm.ask_llm（与 /api/chat 同一实现），注入错误配置：
- auth_error 用例会真实请求 DeepSeek API（预期 401），需要联网；
- network_error / config_error 用例不需要密钥、不需要联网。

运行（项目根目录）：python tests/run_failure_tests.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import llm  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

STATE = {
    "state_id": "A",
    "source_type": "SIMULATED",
    "temperature": 24.0,
    "temperature_unit": "°C",
    "humidity": 65.0,
    "humidity_unit": "%",
    "light": 12000.0,
    "light_unit": "lux",
}
QUESTION = "当前环境怎么样？"

CASES = [
    {
        "name": "错误密钥（预期 auth_error，需联网：真实请求 DeepSeek API 得到 401）",
        "env": {"LLM_API_KEY": "sk-this-is-a-wrong-key-000000", "LLM_BASE_URL": "https://api.deepseek.com",
                "LLM_MODEL": "deepseek-chat", "LLM_TIMEOUT": "20"},
        "expect_type": "auth_error",
    },
    {
        "name": "网络异常（预期 network_error，指向本机未监听端口，无需联网）",
        "env": {"LLM_API_KEY": "sk-fake", "LLM_BASE_URL": "http://127.0.0.1:59999",
                "LLM_MODEL": "deepseek-chat", "LLM_TIMEOUT": "10"},
        "expect_type": "network_error",
    },
    {
        "name": "缺失密钥（预期 config_error，无需联网）",
        "env": {"LLM_API_KEY": "", "LLM_BASE_URL": "https://api.deepseek.com",
                "LLM_MODEL": "deepseek-chat", "LLM_TIMEOUT": "10"},
        "expect_type": "config_error",
    },
]


def run_case(case):
    saved = {}
    for key, value in case["env"].items():
        saved[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        result = llm.ask_llm(state=STATE, question=QUESTION)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("用例：%s" % case["name"])
    print("  期望 error_type: %s | 实际: %s" % (case["expect_type"], result.get("error_type")))
    print("  消息: %s" % result.get("message"))
    if result.get("detail"):
        print("  详情: %s" % result["detail"])
    passed = result.get("status") == "error" and result.get("error_type") == case["expect_type"]
    print("  结论: %s" % ("PASS ✅" if passed else "FAIL ❌"))
    print()
    return passed


def main():
    results = [run_case(c) for c in CASES]
    passed_all = all(results)
    print("失败测试总结论：%s" % ("全部通过 ✅（所有失败场景都明确报错，未伪装成功）" if passed_all else "存在未通过项 ❌"))
    return 0 if passed_all else 1


if __name__ == "__main__":
    sys.exit(main())
