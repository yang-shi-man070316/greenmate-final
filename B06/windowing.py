"""B06 时间窗口切分：按 timestamp 排序，固定输入窗口 + 预测窗口。

- 输入窗口：最近 window_size（默认 6）个采样点（3 小时，30 分钟/点）；
- 预测窗口：未来 prediction_horizon（默认 4，可选 2~4）个点（1~2 小时）；
- 每个样本记录完整时段（window_start/window_end/predict_start/predict_end），
  可回溯到 B02 数据库对应原始时段并重算验证；
- window_size 可修改后重新生成全部样本（prediction_horizon 同样可改）。
"""

from B02 import db as b02_db

DATASET_START = "2026-10-07 00:00:00"  # 7 天数据集起点（B02 基准 336 条）
DATASET_END = "2026-10-13 23:30:00"    # 7 天数据集终点


def load_b02_samples(start=DATASET_START, end=DATASET_END):
    """从 B02 SQLite 读取时间窗口内样本（按 timestamp 升序，原始值）。"""
    conn = b02_db.connect()
    try:
        rows = b02_db.query_series(conn, start, end)
    finally:
        conn.close()
    return rows


def build_windows(samples, window_size=6, prediction_horizon=4):
    """按 timestamp 顺序切窗口（samples 必须已升序）。

    返回窗口列表；每个窗口含：
    - input_points / prediction_points（原始样本切片）
    - window_start / window_end / predict_start / predict_end（可回溯 B02 时段）
    - window_size / prediction_horizon（本窗口使用的配置）
    """
    if window_size < 1:
        raise ValueError("window_size 必须 >= 1")
    if prediction_horizon not in (2, 3, 4):
        raise ValueError("prediction_horizon 必须为 2~4（未来 1~2 小时）")
    n = len(samples)
    windows = []
    for i in range(0, n - window_size - prediction_horizon + 1):
        inputs = samples[i:i + window_size]
        preds = samples[i + window_size:i + window_size + prediction_horizon]
        windows.append({
            "window_index": i,
            "window_size": window_size,
            "prediction_horizon": prediction_horizon,
            "window_start": inputs[0]["timestamp"],
            "window_end": inputs[-1]["timestamp"],
            "predict_start": preds[0]["timestamp"],
            "predict_end": preds[-1]["timestamp"],
            "input_points": inputs,
            "prediction_points": preds,
        })
    return windows


def traceback_to_b02(window, window_size=None):
    """回溯：按窗口时段从 B02 重新查询原始样本并重算特征，验证样本可回溯。

    返回 (input_points, prediction_points, features) —— 与生成时一致则回溯成立。
    """
    from features import extract_features
    rows = load_b02_samples()
    by_ts = {r["timestamp"]: r for r in rows}
    input_points = [by_ts[p["timestamp"]] for p in window["input_points"]]
    prediction_points = [by_ts[p["timestamp"]] for p in window["prediction_points"]]
    return input_points, prediction_points, extract_features(input_points)
