"""S1 LLM 自然语言解释：复用 B01 的 LLM 能力（根 llm.py 的 get_config/map_error）。

使用固定 prompt（任务要求）：
「分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。」

环境数据、历史数据、模型预测、结构化判断全部作为上下文传入；
结构化判断由系统生成，LLM 无权修改，只做解释。
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from llm import LLMError, get_config, map_error  # noqa: E402

FIXED_PROMPT = "分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。"

SYSTEM_PROMPT = (
    "你是 GreenMate 环境分析助手。\n"
    "下面是系统生成的结构化环境分析结果（包含当前环境状态、近期历史、模型预测与结构化判断）。\n"
    "规则：\n"
    "1. 结构化判断由系统生成，你无权修改，只能基于它进行解释；\n"
    "2. 解释必须说明判断依据（引用结构化结果中的数值与字段）；\n"
    "3. 数据均为 SIMULATED 模拟数据，不得暗示为真实测量；\n"
    "4. 用中文回答，简洁。"
)


def explain(payload):
    """payload: {current_state, recent_trend, prediction, judgment}。
    返回 {status, answer, model, elapsed_ms, prompt_used}；失败返回 error 不伪装成功。"""
    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type, "message": e.message}

    user_message = FIXED_PROMPT + "\n\n结构化分析结果：\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        answer = (resp.choices[0].message.content or "").strip()
        return {"status": "success", "answer": answer, "model": model,
                "prompt_used": FIXED_PROMPT,
                "elapsed_ms": round((time.time() - started) * 1000)}
    except Exception as e:
        err = map_error(e, base_url, timeout, round((time.time() - started) * 1000))
        err["status"] = "error"
        return err
