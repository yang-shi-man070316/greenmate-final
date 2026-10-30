"""创新点3 判定：跟随证据条件变化，自动调整表达强度和判断范围。

三组场景（内部证据始终相同：E1 升温历史 + E2 模型 WATCH + E4 知识 K09）：
- run_agree          天气方向=升温（与内部证据一致）→ attention_confirmed（结论相对明确）
- run_conflict       天气方向=降温（与内部证据分歧）→ attention_uncertain（保留分歧，不判定胜负）
- run_missing_weather 天气证据调用失败缺失 → attention_weather_missing（收缩判断边界）

天气方向判定（透明规则）：未来 3 小时温度末点-首点 ≥ +1℃ → warming；≤ -1℃ → cooling。
"""


def weather_direction(weather_evidence):
    """从天气证据判定方向：warming / cooling / neutral。

    兼容两种封装：B05 工具模板（数据在 data 层）与 S4 证据封装（数据在 result 层）。
    """
    payload = (weather_evidence or {}).get("result") or (weather_evidence or {}).get("data") or {}
    hourly = (payload.get("forecast") or {}).get("hourly") or []
    temps = [h.get("temperature_2m") for h in hourly[:3]
             if h.get("temperature_2m") is not None]
    if len(temps) >= 2:
        diff = temps[-1] - temps[0]
        if diff >= 1.0:
            return "warming"
        if diff <= -1.0:
            return "cooling"
    return "neutral"


def build_judgment(mode, adopted_evidence, missing_evidence, weather_evidence=None):
    """三组判定。adopted/missing 与 S5 语义一致。"""
    if mode in ("run_missing_weather", "missing_weather"):
        return {
            "judgment_type": "i3_judgment",
            "verdict": "attention_weather_missing",
            "verdict_note": ("天气证据缺失（调用失败）：内部证据（升温历史+模型 WATCH）指向关注，"
                             "但依赖天气的判断全部受限，判断边界收缩，禁止脑补天气信息"),
            "expression_level": "受限（收缩判断边界）",
            "adopted_evidence": [ev.get("evidence_id") for ev in adopted_evidence],
            "missing_evidence": [{
                "evidence_id": m.get("evidence_id"), "source_type": m.get("source_type"),
                "reason": (m.get("error") or {}).get("message", "未知原因"),
            } for m in missing_evidence],
        }
    direction = weather_direction(weather_evidence)
    if direction == "warming":
        verdict = "attention_confirmed"
        note = ("证据方向一致：历史升温（已发生）+ 模型 WATCH（推断）+ 天气升温（外部条件）"
                "均指向风险，结论可以相对明确")
        expression = "相对明确（证据一致）"
    else:
        verdict = "attention_uncertain"
        note = ("证据分歧：历史升温与模型 WATCH 指向风险，天气预报后续降温（缓解方向）；"
                "不判定证据胜负，保留分歧与不确定性")
        expression = "不确定（保留分歧）"
    return {
        "judgment_type": "i3_judgment",
        "verdict": verdict,
        "verdict_note": note,
        "expression_level": expression,
        "weather_direction": direction,
        "adopted_evidence": [ev.get("evidence_id") for ev in adopted_evidence],
        "missing_evidence": [],
    }
