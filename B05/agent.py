"""B05 Agent 主循环：真实工具调用闭环。

用户任务 → LLM 输出 tool_call（自主选择，顺序不写死）
         → 后端真实执行函数（tools.py，禁止模拟）
         → tool_result 回填 → LLM 判断：继续调用工具 或 输出最终回答。

复用根 llm.py 的 get_config / map_error（密钥与错误映射）。
"""

import json
import time

from openai import OpenAI

from llm import LLMError, get_config, map_error

import tools
from tools import TOOL_META

MAX_ITERATIONS = 5

SYSTEM_PROMPT = (
    "你是 GreenMate 工具智能体。你有 4 个工具可用，必须通过工具获取数据，禁止凭空编造。\n"
    "规则：\n"
    "1. 用户任务需要数据时，调用对应工具；工具调用顺序与组合由你自主决定；\n"
    "2. 工具返回 status=ok 的数据可以作为回答依据，并在回答中说明数据来源；\n"
    "3. 工具返回 status=unavailable 或 error 时，必须明确告诉用户「该证据缺失/不可用」及原因，"
    "不得编造该数据，也不得假装调用成功；\n"
    "4. 需要多步获取信息时逐步调用，全部完成后给出最终回答；\n"
    "5. 用中文回答。"
)

TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": name,
        "description": meta["description"],
        "parameters": meta["parameters"],
    }}
    for name, meta in TOOL_META.items()
]

TOOL_IMPL = {
    "get_current_environment": tools.get_current_environment,
    "get_environment_history": tools.get_environment_history,
    "get_weather_evidence": tools.get_weather_evidence,
    "search_tomato_knowledge": tools.search_tomato_knowledge,
}


def _execute_tool(name, arguments):
    """真实执行工具函数，返回 (tool_result, elapsed_ms)。"""
    started = time.time()
    try:
        impl = TOOL_IMPL.get(name)
        if impl is None:
            result = {"status": "error", "source": "agent", "provider": "greenmate_agent",
                      "retrieved_at": tools._now(),
                      "error": {"error_type": "unknown_tool",
                                "message": "未知工具: %s" % name}}
        else:
            result = impl(**arguments)
    except Exception as e:
        result = {"status": "error", "source": "agent", "provider": "greenmate_agent",
                  "retrieved_at": tools._now(),
                  "error": {"error_type": "execution_error",
                            "message": "%s: %s" % (type(e).__name__, str(e)[:200])}}
    return result, round((time.time() - started) * 1000)


def run_agent(task, max_iterations=MAX_ITERATIONS):
    """执行 Agent 循环。返回 {status, answer, steps, iterations, model}。"""
    task = (task or "").strip()
    if not task:
        return {"status": "error", "error_type": "validation_error",
                "message": "任务不能为空", "steps": [], "iterations": 0}

    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type,
                "message": e.message, "steps": [], "iterations": 0}

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    steps = []
    final_answer = None

    for iteration in range(1, max_iterations + 1):
        # 1. LLM 决策：自主选择工具或输出最终回答
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=TOOLS_SPEC,
                tool_choice="auto", temperature=0)
        except Exception as e:
            err = map_error(e, base_url, timeout, 0)
            return {"status": "error", "error_type": err.get("error_type"),
                    "message": err.get("message"), "detail": err.get("detail"),
                    "steps": steps, "iterations": iteration - 1, "model": model}

        msg = resp.choices[0].message
        if not msg.tool_calls:
            final_answer = (msg.content or "").strip()
            break

        # 2. 逐条真实执行 tool_call
        assistant_msg = msg
        tool_messages = []
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("arguments 不是 JSON 对象")
            except Exception as e:
                arguments = None
                parse_error = "%s: %s（原始参数: %s）" % (
                    type(e).__name__, str(e), tc.function.arguments)

            step = {"iteration": iteration,
                    "tool_call": {"name": name,
                                  "arguments": arguments if arguments is not None else tc.function.arguments or "{}"}}
            if arguments is None:
                step["execution"] = {"elapsed_ms": 0, "real": False, "error": parse_error}
                result = {"status": "error", "source": "agent", "provider": "greenmate_agent",
                          "retrieved_at": tools._now(),
                          "error": {"error_type": "invalid_arguments", "message": parse_error}}
            else:
                result, elapsed = _execute_tool(name, arguments)
                step["execution"] = {"elapsed_ms": elapsed, "real": True}
            step["tool_result"] = result
            steps.append(step)
            tool_messages.append({"role": "tool", "tool_call_id": tc.id,
                                  "content": json.dumps(result, ensure_ascii=False)})

        # 3. tool_result 回填，让 LLM 决定下一步
        messages.append(assistant_msg)
        messages.extend(tool_messages)

    if final_answer is None:
        return {"status": "max_iterations",
                "message": "已达到最大工具调用轮数（%d），未获得最终回答" % max_iterations,
                "answer": "", "steps": steps, "iterations": max_iterations, "model": model}

    return {"status": "ok", "answer": final_answer, "steps": steps,
            "iterations": iteration, "model": model}
