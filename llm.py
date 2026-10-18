"""LLM API 封装（OpenAI 兼容接口，默认 DeepSeek）。

要点：
1. 密钥不硬编码：每次调用从环境变量 / .env 读取（LLM_API_KEY）；
2. 上下文组装：把【环境状态 JSON + 用户问题】显式放进 messages（build_messages）；
3. 失败处理：任何异常都映射为结构化错误（error_type + message），绝不伪装成功。
"""

import json
import os
import time

import openai
from dotenv import load_dotenv
from openai import OpenAI

SYSTEM_PROMPT = (
    "你是 GreenMate 智能环境助手。\n"
    "用户会向你询问当前环境状况。你收到的环境状态数据来自模拟数据源（source_type=SIMULATED）。\n"
    "规则：\n"
    "1. 回答必须基于给定的环境状态数据，并引用具体数值（温度、湿度、光照）。\n"
    "2. 数据中没有的信息不要编造。\n"
    "3. 若环境参数明显不适（如温度过高/过低、湿度过低、光照过强），请指出并给出简要建议。\n"
    "4. 用中文回答，简洁。"
)


class LLMError(Exception):
    def __init__(self, error_type, message):
        self.error_type = error_type
        self.message = message
        super().__init__(message)


def get_config():
    """读取 LLM 配置。每次调用时读取 .env / 环境变量：
    - 密钥不硬编码；
    - 服务运行中修改 .env 无需重启，下一次请求即生效；
    - 便于测试脚本注入错误配置做失败测试。"""
    load_dotenv()  # 只填充未设置的变量，已存在的环境变量优先
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise LLMError(
            "config_error",
            "LLM_API_KEY 未配置：请复制 .env.example 为 .env 并填入真实 API Key",
        )
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()
    model = os.getenv("LLM_MODEL", "deepseek-chat").strip()
    try:
        timeout = float(os.getenv("LLM_TIMEOUT", "30"))
    except ValueError:
        timeout = 30.0
    return api_key, base_url, model, timeout


def build_messages(state, question):
    """把【环境状态 + 用户问题】组装进 LLM 上下文。

    网页展示状态不等于 AI 读取状态：这里显式把状态 JSON 放进
    user message，LLM 才能“读到”当前环境。
    """
    state_json = json.dumps(state, ensure_ascii=False, indent=2)
    user_message = (
        "当前环境状态如下（数据来源：%s）：\n%s\n\n用户问题：%s"
        % (state.get("source_type", "UNKNOWN"), state_json, question)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def map_error(e, base_url, timeout, elapsed_ms):
    """把异常映射为结构化错误。注意：APITimeoutError 是 APIConnectionError
    的子类，必须先判断超时。"""
    name = type(e).__name__
    detail = "%s: %s" % (name, str(e)[:200])

    if isinstance(e, openai.APITimeoutError):
        return {
            "error_type": "timeout",
            "message": "LLM API 请求超时（>%ss），请稍后重试或调大 LLM_TIMEOUT" % timeout,
            "detail": detail,
            "elapsed_ms": elapsed_ms,
        }
    if isinstance(e, openai.AuthenticationError) or getattr(e, "status_code", None) == 401:
        return {
            "error_type": "auth_error",
            "message": "LLM API 认证失败（401）：API Key 无效或已过期，请检查 .env 中的 LLM_API_KEY",
            "detail": detail,
            "elapsed_ms": elapsed_ms,
        }
    if isinstance(e, openai.APIConnectionError):
        cause = str(e.__cause__)[:200] if e.__cause__ else str(e)
        return {
            "error_type": "network_error",
            "message": "网络异常：无法连接 LLM API（base_url=%s），请检查网络或 LLM_BASE_URL" % base_url,
            "detail": "%s: %s" % (name, cause),
            "elapsed_ms": elapsed_ms,
        }
    status_code = getattr(e, "status_code", None)
    if status_code == 402:
        return {
            "error_type": "api_error",
            "message": "LLM API 拒绝请求（HTTP 402）：可能为账户余额不足，请检查账户",
            "detail": detail,
            "elapsed_ms": elapsed_ms,
        }
    if status_code:
        return {
            "error_type": "api_error",
            "message": "LLM API 返回错误（HTTP %s）" % status_code,
            "detail": detail,
            "elapsed_ms": elapsed_ms,
        }
    return {
        "error_type": "unknown",
        "message": "LLM 调用失败（%s）" % name,
        "detail": detail,
        "elapsed_ms": elapsed_ms,
    }


def ask_llm(state, question):
    """调用 LLM。成功返回 {"status": "success", ...}；
    任何失败返回 {"status": "error", ...}，绝不伪装成功。"""
    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type, "message": e.message}

    messages = build_messages(state, question)
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        answer = (resp.choices[0].message.content or "").strip()
        return {
            "status": "success",
            "answer": answer,
            "model": model,
            "state_used": state,       # 实际送入上下文的状态（供页面回显核对）
            "messages_sent": messages,  # 实际发送给 LLM 的完整上下文（供复现）
            "elapsed_ms": round((time.time() - started) * 1000),
        }
    except Exception as e:
        error = map_error(e, base_url, timeout, round((time.time() - started) * 1000))
        error["status"] = "error"
        return error
