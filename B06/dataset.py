"""B06 数据集组装与按时间切分（无时间泄露）。

- 窗口 → 8 个骨架特征 + 透明规则标签（label_source 仅元数据）；
- 时间边界：前 5 天（2026-10-07 ~ 10-11 23:30）训练、后 2 天（10-12 ~ 10-13 23:30）测试；
- 预测窗口跨越边界的样本直接丢弃（不进入任何集合）；
- 训练/测试按时间严格分离：训练样本的 predict_end 全部早于边界，测试样本的
  predict_start 全部不早于边界。
"""

from labeling import label_prediction_window
from features import extract_features
import windowing

TRAIN_END = "2026-10-12 00:00:00"  # 训练段终点（前 5 天）；测试段 = 后 2 天


def build_dataset(window_size=6, prediction_horizon=4):
    """窗口 → 特征 → 标签，返回按时间升序的样本行列表。"""
    samples = windowing.load_b02_samples()
    windows = windowing.build_windows(samples, window_size, prediction_horizon)
    rows = []
    for w in windows:
        feats = extract_features(w["input_points"])
        label, label_source = label_prediction_window(w["prediction_points"])
        row = {
            "window_start": w["window_start"],
            "window_end": w["window_end"],
            "predict_start": w["predict_start"],
            "predict_end": w["predict_end"],
            "label": label,
            "label_source": label_source,
        }
        row.update(feats)
        rows.append(row)
    return rows


def split_train_test(rows, boundary=TRAIN_END):
    """按时间边界切分；预测窗口跨越边界的样本丢弃。

    归属规则：predict_end < boundary 且 window_end < boundary → 训练；
              predict_start >= boundary → 测试；
              其余（预测窗口跨越边界）→ 丢弃。
    """
    train, test, dropped = [], [], []
    for r in rows:
        if r["predict_end"] < boundary and r["window_end"] < boundary:
            train.append(r)
        elif r["predict_start"] >= boundary:
            test.append(r)
        else:
            dropped.append(r)
    return train, test, dropped
