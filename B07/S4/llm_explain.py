"""S4 LLM 合成推理：三部分输出 + 证据绑定 + 禁止强确定性结论。

复用 B01 的 LLM 能力（根 llm.py 的 get_config/map_error）。

输出约束（写入 prompt 并由 check_forbidden 校验）：
- 分成三部分：支持提高关注的证据列表 / 提示情况可能缓解、反向变化的证据列表 /
  当前信息不足以确定的部分；
- 每一段结论标注依赖的证据编号（如 [E1]），可反向回答"这句话主要依据哪些证据"；
- 禁止输出"一定、必然、肯定"等强确定性结论。
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
    "你是 GreenMate 环境分析助手。你会收到多条来自不同数据源的证据和系统结构化判定。\n"
    "回答必须严格遵守以下规则：\n"
    "1. 输出分成三部分：\n"
    "   【支持提高关注的证据】列出支持关注的理由；\n"
    "   【提示情况可能缓解、反向变化的证据】列出与风险方向相反或缓解的理由；\n"
    "   【当前信息不足以确定的部分】列出目前无法确定的内容。\n"
    "2. 每一条结论必须标注其依赖的证据编号（如 [E1] [E2]），编号对应给出的证据清单；\n"
    "3. 禁止输出『一定、必然、肯定、绝对、无疑、必将、注定』等强确定性结论；\n"
    "4. 不强行把分歧证据合并成单一确定结论；\n"
    "5. 用中文回答，简洁。"
)

FORBIDDEN_WORDS = ("一定", "必然", "肯定", "绝对", "无疑", "必将", "注定")


def check_forbidden(text):
    """幻觉约束校验：返回命中的强确定性禁止词列表（空列表 = 通过）。

    排除否定语境：如「不能证明未来一定继续恶化」是引用/否定表述，
    不构成强确定性结论，不计入命中。
    """
    import re
    hits = []
    for w in FORBIDDEN_WORDS:
        for m in re.finditer(re.escape(w), text or ""):
            prefix = (text or "")[max(0, m.start() - 6):m.start()]
            if any(neg in prefix for neg in ("不", "无", "难", "未", "别")):
                continue  # 否定语境，不算强确定性结论
            if w == "一定" and prefix.endswith("有"):
                continue  # 「有一定延续性」是程度副词（有些），不是强确定性结论
            hits.append(w)
    return hits


def build_messages(evidence_list, judgment):
    evidence_text = "\n".join(
        "[%s] source_type=%s source=%s status=%s\n    result=%s%s" % (
            ev.get("evidence_id", "E?"), ev["source_type"], ev["source"], ev["status"],
            json.dumps(ev.get("result"), ensure_ascii=False)[:600],
            (" | error=%s" % json.dumps(ev.get("error"), ensure_ascii=False)) if ev.get("error") else "")
        for ev in evidence_list)
    if not evidence_list:
        evidence_text = "（无证据）"
    user_message = (
        "证据清单：\n%s\n\n"
        "系统结构化判定：verdict=%s（%s）\n"
        "请按三段式规则输出合成推理，每条结论标注证据编号。"
    ) % (evidence_text, judgment["verdict"], judgment["verdict_note"])
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def explain(evidence_list, judgment):
    """LLM 三段式合成推理。返回 {status, answer, forbidden_hits, model, elapsed_ms}。"""
    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type, "message": e.message,
                "forbidden_hits": []}

    messages = build_messages(evidence_list, judgment)
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        answer = (resp.choices[0].message.content or "").strip()
        return {
            "status": "success",
            "answer": answer,
            "forbidden_hits": check_forbidden(answer),
            "model": model,
            "elapsed_ms": round((time.time() - started) * 1000),
        }
    except Exception as e:
        err = map_error(e, base_url, timeout, round((time.time() - started) * 1000))
        err["status"] = "error"
        err["forbidden_hits"] = []
        return err
