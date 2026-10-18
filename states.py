"""模拟环境状态数据与切换逻辑（SIMULATED 数据源）。

StateA / StateB 两组模拟数据，用于 A/B 测试：
同一问题、仅切换状态，验证 LLM 回答是否随环境状态变化并引用数值。
"""

STATES = {
    "A": {
        "state_id": "A",
        "label": "StateA",
        "source_type": "SIMULATED",
        "temperature": 24.0,
        "temperature_unit": "°C",
        "humidity": 65.0,
        "humidity_unit": "%",
        "light": 12000.0,
        "light_unit": "lux",
    },
    "B": {
        "state_id": "B",
        "label": "StateB",
        "source_type": "SIMULATED",
        "temperature": 36.0,
        "temperature_unit": "°C",
        "humidity": 35.0,
        "humidity_unit": "%",
        "light": 22000.0,
        "light_unit": "lux",
    },
}

_current_state_id = "A"


def current_state():
    """返回服务端当前状态（页面展示与 LLM 上下文共用这份数据）。"""
    return dict(STATES[_current_state_id])


def switch_state(state_id):
    """切换当前状态并返回新状态；非法 state_id 抛 ValueError。"""
    global _current_state_id
    state_id = (state_id or "").strip().upper()
    if state_id not in STATES:
        raise ValueError("未知状态: %s，可选: %s" % (state_id, ", ".join(sorted(STATES))))
    _current_state_id = state_id
    return current_state()
