"""B06 标签构造：透明规则生成 next_window_attention（NORMAL / WATCH）。

规则作用于预测窗口内的每个采样点，任一命中即 WATCH，label_source 记录触发的规则
（label_source 仅作审计元数据，禁止进入特征）。

规则阈值设计（对照 B02 基线，基线不触发、扰动触发）：
- temp_high:   温度 > 31℃   （基线峰值 30℃ 不触发；热浪 D1 达 38℃ 触发）
- temp_low:    温度 < 13℃   （基线谷值 14℃ 不触发；冷锋 D3 约 8℃ 触发）
- hum_low:     湿度 < 40%    （基线谷值 45% 不触发；干燥 D5 约 27% 触发）
- hum_high:    湿度 > 85%    （基线峰值 75% 不触发；阴雨 D2 约 87% 触发）
- light_night: 夜间(19:00-6:00)光照 > 500 lux（基线夜间 5 lux 不触发；夜间强光 D4 达 8000 触发）
"""

RULE_DESCRIPTIONS = {
    "temp_high": "温度 > 31℃（高温）",
    "temp_low": "温度 < 13℃（低温）",
    "hum_low": "湿度 < 40%（干燥）",
    "hum_high": "湿度 > 85%（过湿）",
    "light_night": "夜间光照 > 500 lux（夜间光照异常）",
}


def _is_night(timestamp):
    hour = int(timestamp[11:13])
    return hour >= 19 or hour < 6


def label_prediction_window(points):
    """对预测窗口内的采样点应用透明规则，返回 (label, label_source)。"""
    triggers = set()
    for p in points:
        if p["temperature"] > 31:
            triggers.add("temp_high")
        if p["temperature"] < 13:
            triggers.add("temp_low")
        if p["humidity"] < 40:
            triggers.add("hum_low")
        if p["humidity"] > 85:
            triggers.add("hum_high")
        if _is_night(p["timestamp"]) and p["light"] > 500:
            triggers.add("light_night")
    if triggers:
        return "WATCH", "+".join(sorted(triggers))
    return "NORMAL", ""
