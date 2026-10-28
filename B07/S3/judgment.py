"""S3 组合判定：内部稳态基线（复用 S1 判断引擎）+ 外部天气预报维度。

- 内部数据固定（B01 状态 / B02 稳态段 / B06 模型），两轮实验完全一致；
- --with_weather 叠加未来天气预报证据，判定风险升级并归因于外部天气；
- 校验 forecast_time 晚于 analysis_time（retrieved_at）；
- 阴雨低光照识别规则（透明）：未来 3 小时任一小时
  降水概率 ≥60% 或 云量 ≥80% → weather_risk（云量≥80% 时外部光照被显著压低）。
"""

from datetime import datetime

from B07.S1.judgment import build_judgment as build_internal_judgment

RAIN_THRESHOLD = 60   # 降水概率 %
CLOUD_THRESHOLD = 80  # 云量 %（≥80% 视为光照被显著压低）


def _norm_ts(ts):
    return (ts or "").replace("T", " ")


def build_judgment(current, history, prediction, forecast_evidence=None):
    """生成 S3 结构化判断。forecast_evidence 为空 = baseline 场景。"""
    base = build_internal_judgment(current, history, prediction)
    internal_verdict = base["verdict"]

    weather_risk = None
    forecast_valid = None
    if forecast_evidence:
        f = forecast_evidence
        # B05 工具返回统一模板：预报字段在 data 层；同时兼容裸 B03 evidence 结构
        data = f.get("data") or f
        # 校验：forecast_time 必须晚于 analysis_time（此处取 retrieved_at）
        analysis_time = f.get("retrieved_at") or base.get("generated_at")
        forecast_times = data.get("forecast_time") or []
        forecast_valid = bool(forecast_times) and all(
            _norm_ts(ts) > analysis_time for ts in forecast_times[:1])
        # 阴雨低光照识别（未来 3 小时）
        next3 = (data.get("forecast") or {}).get("hourly", [])[:3]
        rainy = any(h.get("precipitation_probability", 0) >= RAIN_THRESHOLD for h in next3)
        overcast = any(h.get("cloud_cover", 0) >= CLOUD_THRESHOLD for h in next3)
        if rainy or overcast:
            weather_risk = {
                "alert": "未来阴雨低光照预报",
                "precipitation_probability_3h": [h.get("precipitation_probability") for h in next3],
                "cloud_cover_3h": [h.get("cloud_cover") for h in next3],
                "low_light_expected": overcast,
                "reason": ("未来 3 小时降水概率≥%d%% 或云量≥%d%%，外部天气将显著压低光照"
                           "（云量≥%d%% 时估算光照 <2000 lux），影响番茄生长环境" % (
                               RAIN_THRESHOLD, CLOUD_THRESHOLD, CLOUD_THRESHOLD)),
            }

    if weather_risk and forecast_valid:
        verdict = "weather_attention"
        attribution = "external_weather"
    else:
        verdict = internal_verdict
        attribution = "none"

    judgment = dict(base)
    judgment.update({
        "judgment_type": "s3_combined_judgment",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": verdict,
        "internal_verdict": internal_verdict,
        "attribution": attribution,
        "weather_risk": weather_risk,
        "forecast_time_valid": forecast_valid,
        "weather_forecast": forecast_evidence,
    })
    if attribution == "external_weather":
        judgment["judgment_limits"] = base.get("judgment_limits", []) + [
            "风险升级完全归因于外部天气预报（内部稳态判定不变），天气证据参与推理而非仅展示"]
    return judgment
