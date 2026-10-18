"""B04 最小检索逻辑：关键词打分 + Top-K，无数据库、无索引、无 Embedding。

- 知识库：本地 JSON 文件（knowledge/knowledge_base.json），进程内加载；
- 打分：query 与片段 keywords 的双向子串匹配（命中 +2），topic 匹配（+1）；
- 检索结果可追溯：每条证据含 id / topic / scope / content / source /
  retrieved_at / score / matched_keywords；
- 分数为 0 的片段不进结果：没有相关知识时返回空列表，调用方不得编造。
"""

import json
from datetime import datetime
from pathlib import Path

KNOWLEDGE_FILE = Path(__file__).resolve().parent / "knowledge" / "knowledge_base.json"

_cache = None


def load_segments():
    """加载本地知识片段（进程内缓存）。"""
    global _cache
    if _cache is None:
        with open(KNOWLEDGE_FILE, encoding="utf-8") as f:
            _cache = json.load(f)["segments"]
    return _cache


def normalize(text):
    return (text or "").strip().lower().replace(" ", "")


def _score(segment, query):
    """关键词双向子串匹配打分，返回 (score, matched_keywords)。"""
    score = 0
    matched = []
    for kw in segment.get("keywords", []):
        kw_n = normalize(kw)
        if kw_n and (kw_n in query or query in kw_n):
            score += 2
            matched.append(kw)
    topic_n = normalize(segment.get("topic", ""))
    if topic_n and (topic_n in query or query in topic_n):
        score += 1
    return score, matched


def retrieve(query, top_k=3):
    """检索 Top-K 相关知识片段。无命中返回空列表（禁止编造）。"""
    q = normalize(query)
    if not q:
        return []
    scored = []
    for seg in load_segments():
        s, matched = _score(seg, q)
        if s > 0:
            scored.append((s, matched, seg))
    scored.sort(key=lambda x: -x[0])
    retrieved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    evidence = []
    for s, matched, seg in scored[:top_k]:
        evidence.append({
            "id": seg["id"],
            "topic": seg["topic"],
            "scope": seg["scope"],
            "content": seg["content"],
            "source": seg["source"],
            "retrieved_at": retrieved_at,
            "score": s,
            "matched_keywords": matched,
        })
    return evidence


# 环境相关触发词：问题命中其中之一，才把状态数值注入检索 query。
# 这样库外问题（如「火星土壤 pH」）不会被状态数值污染出伪命中，
# 「检索为空 → 未找到相关知识」的验收场景才真实可达。
ENV_TRIGGER_WORDS = (
    "温度", "气温", "湿度", "光照", "lux", "环境", "植物", "绿植", "养护",
    "高温", "干燥", "潮湿", "炎热", "强光", "灼伤", "遮阴", "通风", "加湿",
    "怎么样", "如何处理", "处理", "℃", "%",
)


def build_query(question, state):
    """拼检索 query：问题 + （问题与环境相关时）状态数值摘要。

    状态关键词只在问题提到环境相关内容时参与检索，避免库外问题被污染。
    """
    q = question or ""
    parts = [q]
    q_norm = normalize(q)
    if state and any(normalize(w) in q_norm for w in ENV_TRIGGER_WORDS):
        parts.append(
            "温度%s 湿度%s 光照%s"
            % (state.get("temperature", ""), state.get("humidity", ""), state.get("light", ""))
        )
    return " ".join(parts)
