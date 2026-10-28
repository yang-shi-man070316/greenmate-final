"""S4 分歧场景判定：多源证据 → 三部分合成，不强行合并单一确定结论。

固定分歧场景：
- E1 B02 历史时序：持续升温 → 支持提高关注
- E2 B06 模型：WATCH → 支持提高关注
- E3 B03 天气：未来降温 → 提示情况可能缓解/反向变化
- E4 B04 知识：持续高温值得关注，但不能证明未来一定继续恶化 → 当前信息不足以确定

三部分合成结构（每条结论绑定证据，可反向回答"这句话依据哪些证据"）：
- support_attention：支持提高关注的证据列表
- mitigating_or_reverse：提示情况可能缓解、反向变化的证据列表
- insufficient：当前信息不足以确定的部分

verdict 规则（透明）：
- 仅 E1+E2（baseline）→ attention（内部证据一致指向风险）
- 叠加 E3+E4（with_evidence）→ attention_uncertain（关注但存在缓解信号与不确定性）
"""


def classify_evidence(evidence_list):
    """按证据 source_type 分类并给出方向与绑定。"""
    directions = {
        "internal_history": "support_attention",
        "ml_prediction": "support_attention",
        "external_weather": "mitigating_or_reverse",
        "local_knowledge": "insufficient",
    }
    classified = {k: [] for k in ("support_attention", "mitigating_or_reverse", "insufficient")}
    for ev in evidence_list:
        direction = directions.get(ev.get("source_type"), "insufficient")
        classified[direction].append(ev)
    return classified


def build_judgment(evidence_list, log=None):
    """evidence_list: 已被采用的证据列表（顺序固定 E1..E4 便于编号）。"""
    registry = {}
    for i, ev in enumerate(evidence_list, start=1):
        ev_id = "E%d" % i
        registry[ev_id] = {
            "source_type": ev["source_type"], "source": ev["source"],
            "status": ev["status"], "direction": classify_evidence([ev]) and None,
        }
        registry[ev_id]["direction"] = (
            "support_attention" if ev["source_type"] in ("internal_history", "ml_prediction")
            else "mitigating_or_reverse" if ev["source_type"] == "external_weather"
            else "insufficient")
        ev["evidence_id"] = ev_id  # 绑定证据编号（供 LLM 与反向查询）

    synthesis = classify_evidence(evidence_list)
    has_weather = any(ev["source_type"] == "external_weather" for ev in evidence_list)
    has_knowledge = any(ev["source_type"] == "local_knowledge" for ev in evidence_list)

    if not has_weather and not has_knowledge:
        verdict = "attention"
        verdict_note = "内部证据（持续升温历史 + 模型 WATCH）一致指向风险"
    else:
        verdict = "attention_uncertain"
        verdict_note = ("内部证据支持提高关注，但外部天气提示可能缓解、"
                        "专业知识提示趋势不能证明未来一定恶化——存在分歧，"
                        "不强行合并为单一确定结论")

    return {
        "judgment_type": "s4_divergent_judgment",
        "verdict": verdict,
        "verdict_note": verdict_note,
        "synthesis": synthesis,          # 三部分：support_attention / mitigating_or_reverse / insufficient
        "evidence_registry": registry,   # 证据编号 → 来源/状态/方向（反向查询用）
        "evidence_count": len(evidence_list),
    }


def explain_conclusion(judgment, conclusion_id):
    """反向回答：这条结论主要依据哪些证据。"""
    found = []
    for part in ("support_attention", "mitigating_or_reverse", "insufficient"):
        for ev in judgment["synthesis"].get(part, []):
            if ev.get("evidence_id") == conclusion_id or ev.get("source") == conclusion_id:
                found.append((part, ev))
    if not found:
        return "未找到结论 %s 对应的证据" % conclusion_id
    lines = ["结论 %s 主要依据以下证据：" % conclusion_id]
    for part, ev in found:
        lines.append("  - %s（source_type=%s, source=%s, status=%s, 方向=%s）" % (
            ev.get("evidence_id"), ev["source_type"], ev["source"], ev["status"], part))
    return "\n".join(lines)
