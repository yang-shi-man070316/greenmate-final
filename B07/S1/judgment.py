"""S1 结构化判断引擎：优先生成、独立存储，LLM 无权修改。

结构化字段（任务要求）：
- current_state      当前环境状态（B05 get_current_environment，SIMULATED）
- recent_trend       近期趋势（最近 3 小时历史统计 + 持续升降检测）
- predicted_attention 模型预测（B06 已训模型原样输出，严禁修改）
- model_version      模型版本
- evidence_status    当前证据状态（数据完整性/来源）
- judgment_limits    当前判断限制

判断规则（透明）：
- 数据稳定 + 模型 NORMAL            → stable
- 数据稳定 + 模型 WATCH             → model_disagreement（只标记，不修改模型结果）
- 数据不稳定                        → attention
- 证据不足                          → inconclusive
"""

from datetime import datetime


def trend_of(samples):
    """对时间序列样本计算近期趋势：范围、均值、前后半均值差（持续升降检测）。"""
    if not samples:
        return {"available": False, "note": "无历史样本"}
    fields = ("temperature", "humidity", "light")
    half = len(samples) // 2
    trend = {"available": True, "count": len(samples),
             "window": "%s ~ %s" % (samples[0]["timestamp"], samples[-1]["timestamp"])}
    stable = True
    for f in fields:
        vals = [p[f] for p in samples]
        first_half = vals[:half]
        second_half = vals[half:]
        # 前后半均值差（两半各自求均值再相减；两半长度可能不等，必须按各自长度归一）
        slope = (sum(second_half) / len(second_half)) - (sum(first_half) / len(first_half))
        trend[f] = {"min": round(min(vals), 1), "max": round(max(vals), 1),
                    "mean": round(sum(vals) / len(vals), 1),
                    "half_diff": round(slope, 2)}  # 后半均值-前半均值
    t = trend["temperature"]
    h = trend["humidity"]
    t_stable = (t["max"] - t["min"]) <= 2.0 and abs(t["half_diff"]) <= 0.5
    h_stable = (h["max"] - h["min"]) <= 10.0 and abs(h["half_diff"]) <= 3.0
    scenarios = sorted(set(p.get("sim_scenario", "?") for p in samples))
    trend["data_stable"] = t_stable and h_stable and scenarios == ["normal"]
    trend["sim_scenarios"] = scenarios
    return trend


def build_judgment(current_env, history_result, prediction):
    """生成结构化判断。prediction 必须来自 B06 模型原样输出，本函数不修改。"""
    samples = (history_result.get("data") or {}).get("samples") or []
    recent_trend = trend_of(samples)
    model_attention = (prediction or {}).get("predicted_attention")
    model_version = (prediction or {}).get("model_version")

    if not samples:
        verdict = "inconclusive"
        data_stable = False
    else:
        data_stable = recent_trend.get("data_stable", False)
        if model_attention is None:
            verdict = "inconclusive"
        elif data_stable and model_attention == "NORMAL":
            verdict = "stable"
        elif data_stable and model_attention == "WATCH":
            verdict = "model_disagreement"
        else:
            verdict = "attention"

    judgment = {
        "judgment_type": "structured_judgment",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": verdict,                       # stable / attention / model_disagreement / inconclusive
        "current_state": current_env,             # 当前环境状态（SIMULATED）
        "recent_trend": recent_trend,             # 近期趋势
        "predicted_attention": model_attention,   # 模型输出，原样保留
        "model_version": model_version,
        "model_output_modified": False,           # 严禁修改模型返回结果
        "model_disagreement_note": (
            "模型输出 WATCH 与近期数据稳定性不符：如实标记为 model_disagreement，"
            "未修改模型结果" if verdict == "model_disagreement" else None),
        "evidence_status": {
            "current_env_source": (current_env or {}).get("source", "unknown"),
            "history_source": (history_result or {}).get("source", "unknown"),
            "history_status": (history_result or {}).get("status", "unknown"),
            "history_sample_count": len(samples),
            "prediction_source": "B06 RandomForest（已训练模型，未重新训练）",
        },
        "judgment_limits": [
            "全部数据为 SIMULATED 模拟数据，非真实传感器读数",
            "趋势判定仅基于最近 3 小时（6 个采样点）",
            "模型预测基于 B02 历史分布训练，时间外推存在不确定性",
            "结构化判断由系统生成，LLM 无权修改，仅用于解释",
        ],
    }
    return judgment
