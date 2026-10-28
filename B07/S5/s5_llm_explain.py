"""S5 证据退化 LLM 推理：两块式输出（可判断内容 + 受限说明）。

- 复用 B01 的 LLM 能力（根 llm.py 的 get_config/map_error）；
- 强制两块：
  【可判断内容】基于剩余有效证据尽力推理，禁止直接回复"无法分析"；
  【受限说明】清晰写明哪一项证据缺失、哪些判断因此不可靠，禁止编造缺失数据；
- 固定提问由调用方传入（两组实验完全一致）。
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from llm import LLMError, get_config, map_error  # noqa: E402

SYSTEM_PROMPT = (
    "你是 GreenMate 环境分析助手。系统会给出有效证据清单、缺失证据清单和结构化判定。\n"
    "回答必须严格分为两块：\n"
    "【可判断内容】基于剩余有效证据进行推理并给出判断；即使部分证据缺失，也必须尽力分析，"
    "禁止直接回复『无法分析』；每条判断标注依据的证据编号（如 [E1]）；\n"
    "【受限说明】清晰写明：哪一项证据缺失、缺失原因、哪些判断因此不可靠；"
    "禁止编造缺失数据或假装证据存在。\n"
    "用中文回答，简洁。"
)


def build_messages(fixed_question, adopted_evidence, missing_evidence, judgment):
    ev_text = "\n".join(
        "[%s] source_type=%s source=%s status=%s\n    result=%s" % (
            ev.get("evidence_id", "E?"), ev["source_type"], ev["source"], ev["status"],
            json.dumps(ev.get("result"), ensure_ascii=False)[:500])
        for ev in adopted_evidence) or "（无有效证据）"
    missing_text = "\n".join(
        "- %s：source_type=%s，缺失原因：%s" % (
            m.get("evidence_id"), m.get("source_type"), m.get("reason"))
        for m in judgment["missing_evidence"]) or "（无）"
    user_message = (
        "%s\n\n"
        "有效证据清单：\n%s\n\n"
        "缺失证据清单：\n%s\n\n"
        "系统结构化判定：verdict=%s（%s）\n"
        "请按两块式规则输出。"
    ) % (fixed_question, ev_text, missing_text, judgment["verdict"], judgment["verdict_note"])
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def explain(fixed_question, adopted_evidence, missing_evidence, judgment):
    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type, "message": e.message}

    messages = build_messages(fixed_question, adopted_evidence, missing_evidence, judgment)
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        answer = (resp.choices[0].message.content or "").strip()
        return {
            "status": "success",
            "answer": answer,
            "has_judgable_section": "可判断内容" in answer,
            "has_limitation_section": "受限说明" in answer,
            "model": model,
            "elapsed_ms": round((time.time() - started) * 1000),
        }
    except Exception as e:
        err = map_error(e, base_url, timeout, round((time.time() - started) * 1000))
        err["status"] = "error"
        return err
