"""创新点3 LLM 推理：两块式输出 + 表达强度跟随证据条件 + 禁止强确定词与脑补。

复用：B01 LLM 能力（根 llm）、S4 的禁止词校验（check_forbidden）。
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from llm import LLMError, get_config, map_error  # noqa: E402
from B07.S4.llm_explain import check_forbidden  # noqa: E402 （复用禁止词校验）

SYSTEM_PROMPT = (
    "你是 GreenMate 环境分析助手。回答必须严格分为两块：\n"
    "【可判断内容】基于有效证据进行推理；\n"
    "【受限说明】写明证据缺失及因此不可靠的判断。\n"
    "表达要求（跟随证据条件自动调整，可信不是大胆下定论，而是知道什么时候该保留）：\n"
    "- 证据方向一致时，结论可以相对明确；\n"
    "- 证据存在分歧时，保留分歧与不确定性，不判定证据胜负；\n"
    "- 证据缺失时，收缩判断边界，只讨论剩余证据可支撑的内容；\n"
    "- 禁止输出『一定、必然、肯定、绝对、无疑、必将、注定』等强确定性结论；\n"
    "- 禁止依靠常识脑补补齐缺失证据（如天气数据缺失时编造天气信息）。\n"
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
        for m in judgment.get("missing_evidence", [])) or "（无）"
    user_message = (
        "%s\n\n"
        "有效证据清单：\n%s\n\n"
        "缺失证据清单：\n%s\n\n"
        "系统判定：verdict=%s（%s）| 表达强度要求：%s\n"
        "请按两块式规则输出，表达强度与判断范围跟随证据条件。"
    ) % (fixed_question, ev_text, missing_text,
         judgment["verdict"], judgment["verdict_note"], judgment.get("expression_level", "—"))
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def explain(fixed_question, adopted_evidence, missing_evidence, judgment):
    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type, "message": e.message,
                "forbidden_hits": []}

    messages = build_messages(fixed_question, adopted_evidence, missing_evidence, judgment)
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        answer = (resp.choices[0].message.content or "").strip()
        return {
            "status": "success",
            "answer": answer,
            "forbidden_hits": check_forbidden(answer),
            "has_judgable_section": "可判断内容" in answer,
            "has_limitation_section": "受限说明" in answer,
            "model": model,
            "elapsed_ms": round((time.time() - started) * 1000),
        }
    except Exception as e:
        err = map_error(e, base_url, timeout, round((time.time() - started) * 1000))
        err["status"] = "error"
        err["forbidden_hits"] = []
        return err
