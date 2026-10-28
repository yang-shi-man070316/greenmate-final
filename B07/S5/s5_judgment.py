"""S5 证据退化判定：区分有效证据与缺失证据，基于剩余证据推理并标注局限。

- 复用 S4 的方向分类（classify_evidence）；
- 缺失证据（status != ok 或 no_match）不进合成，单独记录缺失原因；
- verdict 规则（透明）：
    无缺失                          → attention_uncertain（S4 基线结论）
    缺失 external_weather           → attention_weather_missing（缓解方向失去证据）
    缺失 local_knowledge            → attention_knowledge_missing（不确定性依据失去证据）
    缺失内部证据（历史/模型）        → inconclusive_degraded（核心证据缺失）
"""

from B07.S4.judgment import classify_evidence  # 复用 S4 组件，不新增模块


def is_missing(ev):
    """证据是否缺失：status 非 ok，或 RAG 检索不足（no_match）。"""
    if ev.get("status") != "ok":
        return True
    return bool((ev.get("result") or {}).get("no_match"))


def build_judgment(adopted_evidence, missing_evidence):
    synthesis = classify_evidence(adopted_evidence)
    missing_types = [m.get("source_type") for m in missing_evidence]

    if not missing_evidence:
        verdict = "attention_uncertain"
        note = "全部证据有效（S4 基线结论）"
    elif "internal_history" in missing_types or "ml_prediction" in missing_types:
        verdict = "inconclusive_degraded"
        note = "内部核心证据（历史/模型）缺失，仅剩外部证据不足以独立判断风险"
    elif "external_weather" in missing_types:
        verdict = "attention_weather_missing"
        note = "天气证据缺失：无法评估未来降温等缓解/反向变化，风险判断失去天气维度"
    elif "local_knowledge" in missing_types:
        verdict = "attention_knowledge_missing"
        note = "专业知识证据缺失：缺少『趋势不能证明未来恶化』的不确定性依据"
    else:
        verdict = "attention_uncertain"
        note = "未知缺失类型，按保守处理"

    return {
        "judgment_type": "s5_degraded_judgment",
        "verdict": verdict,
        "verdict_note": note,
        "degraded": bool(missing_evidence),
        "synthesis": synthesis,
        "adopted_evidence": [ev.get("evidence_id") for ev in adopted_evidence],
        "missing_evidence": [{
            "evidence_id": m.get("evidence_id"),
            "source_type": m.get("source_type"),
            "source": m.get("source"),
            "status": m.get("status"),
            "reason": (m.get("error") or {}).get("message") if m.get("error")
            else "RAG 检索无匹配结果（检索不足）" if (m.get("result") or {}).get("no_match")
            else "未知原因",
        } for m in missing_evidence],
    }
