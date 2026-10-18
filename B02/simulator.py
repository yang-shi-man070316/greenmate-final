"""7 天环境模拟器：正常昼夜基线 + 缓慢变化 + 扰动片段 + 过渡 + 噪声。

- 固定 30 分钟一个采样点，7 天 = 336 个点（TOTAL_SAMPLES）；
- sim_scenario 字段只记录模拟器元数据（normal / 扰动id / 扰动id:ramp_in|ramp_out），
  不是标签：任何后续建模任务都不应把它当作 label 使用；
- 固定随机种子，生成结果可复现。
"""

import math
import random
from datetime import datetime, timedelta

SAMPLE_INTERVAL_MINUTES = 30
DAYS = 7
TOTAL_SAMPLES = DAYS * 24 * 60 // SAMPLE_INTERVAL_MINUTES  # 336

DEFAULT_END = datetime(2026, 10, 14, 0, 0)  # 默认时间轴终点（7 天前为起点）
DEFAULT_SEED = 42

# 数值合法范围（quality_check 同样使用）
RANGES = {"temperature": (0.0, 50.0), "humidity": (0.0, 100.0), "light": (0.0, 120000.0)}

# 噪声标准差（light 为相对 3% + 小绝对抖动）
NOISE_SIGMA = {"temperature": 0.25, "humidity": 1.2, "light": 0.03}
LIGHT_ABS_NOISE = 0.5

RAMP_SAMPLES = 2  # 每个扰动前后各 2 个采样点（1 小时）线性过渡

# 扰动清单：4~6 个片段，分散在 7 天内
# add: 加性扰动；factor: 乘性扰动；add["light_override"]: 光照直接覆盖（混合过渡）
DISTURBANCES = [
    {
        "id": "D1", "type": "heat_wave",
        "start": datetime(2026, 10, 8, 12, 0), "end": datetime(2026, 10, 8, 18, 0),
        "description": "热浪：温度 +8℃，湿度 -15%，光照 +10%",
        "add": {"temperature": 8.0, "humidity": -15.0},
        "factor": {"light": 1.10},
    },
    {
        "id": "D2", "type": "overcast_rain",
        "start": datetime(2026, 10, 9, 6, 0), "end": datetime(2026, 10, 9, 18, 0),
        "description": "阴雨：光照 ×0.15，湿度 +12%，温度 -2℃",
        "add": {"temperature": -2.0, "humidity": 12.0},
        "factor": {"light": 0.15},
    },
    {
        "id": "D3", "type": "cold_front",
        "start": datetime(2026, 10, 10, 18, 0), "end": datetime(2026, 10, 11, 6, 0),
        "description": "冷锋过境：温度 -6℃，湿度 +10%",
        "add": {"temperature": -6.0, "humidity": 10.0},
        "factor": {},
    },
    {
        "id": "D4", "type": "night_light_anomaly",
        "start": datetime(2026, 10, 11, 21, 0), "end": datetime(2026, 10, 11, 23, 30),
        "description": "夜间强光异常：光照恒定 8000 lux",
        "add": {"light_override": 8000.0},
        "factor": {},
    },
    {
        "id": "D5", "type": "dry_dust",
        "start": datetime(2026, 10, 12, 0, 0), "end": datetime(2026, 10, 13, 0, 0),
        "description": "干燥沙尘：湿度 -18%，温度 +3℃，光照 ×0.8",
        "add": {"temperature": 3.0, "humidity": -18.0},
        "factor": {"light": 0.80},
    },
]


def _baseline(ts):
    """正常昼夜基线（由当日小时数驱动，缓慢变化）：
    - 光照：6:00–18:00 正弦，正午峰值 55000 lux；夜间 5 lux；
    - 温度：日较差 16℃（峰值 30℃ 在 15:00，谷值 14℃ 在 3:00）；
    - 湿度：与温度反相（45%–75%）。
    """
    h = ts.hour + ts.minute / 60.0
    if 6.0 <= h <= 18.0:
        light = 55000.0 * math.sin(math.pi * (h - 6.0) / 12.0)
    else:
        light = 5.0
    temp = 22.0 + 8.0 * math.sin(2 * math.pi * (h - 9.0) / 24.0)
    hum = 60.0 - 15.0 * math.sin(2 * math.pi * (h - 9.0) / 24.0)
    return {"temperature": temp, "humidity": hum, "light": light}


def _disturbance_weight(d, ts, ramp_seconds):
    """扰动权重 0→1（含前后 ramp 线性过渡）。
    返回 (weight, phase)，phase: 'core' | 'ramp_in' | 'ramp_out' | None。"""
    start, end = d["start"], d["end"]
    ramp = timedelta(seconds=ramp_seconds)
    if start + ramp <= ts < end - ramp:
        return 1.0, "core"
    if start <= ts < start + ramp:
        return (ts - start).total_seconds() / ramp_seconds, "ramp_in"
    if end - ramp <= ts < end:
        return (end - ts).total_seconds() / ramp_seconds, "ramp_out"
    return 0.0, None


def generate_samples(start_dt, n, seed=DEFAULT_SEED):
    """从 start_dt 起生成 n 个连续采样点（步长 30 分钟）。"""
    rng = random.Random(seed)
    ramp_seconds = RAMP_SAMPLES * SAMPLE_INTERVAL_MINUTES * 60
    samples = []
    for i in range(n):
        ts = start_dt + timedelta(minutes=SAMPLE_INTERVAL_MINUTES * i)
        base = _baseline(ts)

        # 叠加扰动（含 ramp 过渡）
        values = dict(base)
        active = []  # (weight, phase, dist)
        for d in DISTURBANCES:
            w, phase = _disturbance_weight(d, ts, ramp_seconds)
            if w > 0:
                active.append((w, phase, d))
                for field, delta in d.get("add", {}).items():
                    if field == "light_override":
                        values["light"] = values["light"] * (1 - w) + delta * w
                    else:
                        values[field] = values[field] + delta * w
                for field, factor in d.get("factor", {}).items():
                    values[field] = values[field] * (1 + w * (factor - 1))

        # sim_scenario：模拟器元数据，不是标签
        core = [a for a in active if a[1] == "core"]
        ramps = [a for a in active if a[1] != "core"]
        if core:
            scenario = core[0][2]["id"]
        elif ramps:
            _, phase, d = ramps[0]
            scenario = "%s:%s" % (d["id"], phase)
        else:
            scenario = "normal"

        # 噪声
        values["temperature"] += rng.gauss(0, NOISE_SIGMA["temperature"])
        values["humidity"] += rng.gauss(0, NOISE_SIGMA["humidity"])
        values["light"] *= 1 + rng.gauss(0, NOISE_SIGMA["light"])
        values["light"] += rng.gauss(0, LIGHT_ABS_NOISE)

        # clamp 到合法范围并保留合理精度
        values["temperature"] = round(min(max(values["temperature"], RANGES["temperature"][0]), RANGES["temperature"][1]), 1)
        values["humidity"] = round(min(max(values["humidity"], RANGES["humidity"][0]), RANGES["humidity"][1]), 1)
        values["light"] = round(min(max(values["light"], RANGES["light"][0]), RANGES["light"][1]))

        samples.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "temperature": values["temperature"],
            "humidity": values["humidity"],
            "light": values["light"],
            "source_type": "SIMULATED",
            "sim_scenario": scenario,
        })
    return samples


def generate_timeline(end=None, seed=DEFAULT_SEED):
    """生成默认 7 天 336 个连续采样点。"""
    end = end or DEFAULT_END
    start = end - timedelta(days=DAYS)
    return generate_samples(start, TOTAL_SAMPLES, seed=seed)
