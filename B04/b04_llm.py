"""B04 LLM 调用：问题 + 检索知识片段 + 推理要求 组装进上下文。

- 复用根目录 llm.py 的 get_config / map_error（密钥读取与错误映射，不重复实现）；
- 上下文结构：问题 + 环境状态 + 检索到的知识片段（evidence）+ 推理要求；
- system prompt 强制「来自检索知识」与「模型自身推断」分离标注；
- 检索为空时强制「未找到相关知识」，严禁编造。
"""

import json
import time

from openai import OpenAI

from llm import LLMError, get_config, map_error

SYSTEM_PROMPT = (
    "你是 GreenMate 环境助手。回答时必须严格遵守以下规则：\n"
    "1. 只有「相关知识片段」部分提供的知识可以作为知识依据，引用时标注 [依据知识: <片段id>]；\n"
    "2. 知识片段之外的一切陈述都是你自己的推断，必须标注 [推断]；\n"
    "3. 如果「相关知识片段」为空，必须首先明确说明「未找到相关知识」，"
    "可以基于环境状态给出谨慎的一般性提示，但必须标注 [推断]，严禁编造知识性结论；\n"
    "4. 不得虚构任何不存在的引用来源。\n"
    "5. 用中文回答，简洁。"
)


def build_messages(question, state, evidence):
    """组装上下文：问题 + 状态 + 知识片段 + 推理要求。"""
    state_json = json.dumps(state, ensure_ascii=False, indent=2) if state else "（未提供）"
    if evidence:
        lines = ["检索到的相关知识片段（来自本地知识库，Top-%d）：" % len(evidence)]
        for e in evidence:
            lines.append(
                "[%s] %s（scope: %s）\n%s\n来源: %s（检索时间: %s，匹配: %s）"
                % (e["id"], e["topic"], e["scope"], e["content"], e["source"],
                   e["retrieved_at"], ", ".join(e.get("matched_keywords", [])))
            )
        evidence_text = "\n\n".join(lines)
    else:
        evidence_text = "检索到的相关知识片段：空（未检索到任何相关知识）"
    user_message = (
        "用户问题：%s\n\n"
        "当前环境状态：\n%s\n\n"
        "%s\n\n"
        "请回答用户问题。"
    ) % (question, state_json, evidence_text)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def ask_with_knowledge(question, state, evidence):
    """调用 LLM。返回 {status, answer, has_knowledge, ...}；失败返回 error，不编造结论。"""
    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type, "message": e.message}

    messages = build_messages(question, state, evidence)
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        answer = (resp.choices[0].message.content or "").strip()
        return {
            "status": "success",
            "answer": answer,
            "has_knowledge": bool(evidence),
            "model": model,
            "messages_sent": messages,
            "elapsed_ms": round((time.time() - started) * 1000),
        }
    except Exception as e:
        error = map_error(e, base_url, timeout, round((time.time() - started) * 1000))
        error["status"] = "error"
        return error
