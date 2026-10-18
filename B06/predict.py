"""B06 最新窗口推理：B02 最新 6 个点 → 8 骨架特征 → 模型预测。

输出 predicted_attention + model_version，标记 MODEL_OUTPUT；
与 B03 天气证据、B04 知识证据严格分离，并说明不确定性与适用边界。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

import numpy as np  # noqa: E402
from B02 import db as b02_db  # noqa: E402

from features import FEATURE_NAMES, extract_features, feature_vector  # noqa: E402
from train import CONFIG, load_model  # noqa: E402

LATEST_FILE = ROOT / "models" / "latest_prediction.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def predict_latest(window_size=None):
    """取 B02 最新 window_size 个采样点做推理。"""
    window_size = window_size or CONFIG["window_size"]
    conn = b02_db.connect()
    try:
        rows = b02_db.query_series(conn)
        points = rows[-window_size:]  # 最新 6 点（升序尾部）
    finally:
        conn.close()
    if len(points) < window_size:
        raise ValueError("B02 样本不足 %d 点，无法做最新窗口推理" % window_size)

    feats = extract_features(points)
    vec = np.array([feature_vector(feats)])

    model, metadata = load_model()
    proba = model.predict_proba(vec)[0]
    classes = list(model.classes_)
    pred = classes[int(np.argmax(proba))]
    prob_map = {c: round(float(p), 4) for c, p in zip(classes, proba)}
    confidence = max(prob_map.values())

    result = {
        "prediction_type": "attention_prediction",
        "output_marker": "MODEL_OUTPUT",  # 与 B03 天气证据 / B04 知识证据区分
        "predicted_attention": pred,
        "probability": prob_map,
        "model_version": metadata["model_version"],
        "trained_at": metadata["trained_at"],
        "features_used": feats,
        "feature_names": FEATURE_NAMES,
        "input_window": {
            "window_size": window_size,
            "start": points[0]["timestamp"],
            "end": points[-1]["timestamp"],
        },
        "uncertainty": ("置信度 %.1f%%，低于 70%% 阈值，预测仅作参考" % (confidence * 100)
                        if confidence < 0.7 else
                        "置信度 %.1f%%（基于历史 SIMULATED 数据训练）" % (confidence * 100)),
        "applicability": (
            "适用边界：仅适用于 B02 SIMULATED 模拟数据（30 分钟网格、同一模拟器规则）；"
            "本预测独立于 B03 外部天气证据与 B04 本地知识证据，三者不可混用；"
            "对超出训练分布的真实环境不具备泛化保证。"),
    }
    LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    LATEST_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    result = predict_latest()
    print("[MODEL_OUTPUT] predicted_attention=%s | model_version=%s" % (
        result["predicted_attention"], result["model_version"]))
    print("[概率] %s" % result["probability"])
    print("[输入窗口] %s ~ %s（%d 点）" % (
        result["input_window"]["start"], result["input_window"]["end"], result["input_window"]["window_size"]))
    print("[特征] %s" % result["features_used"])
    print("[不确定性] %s" % result["uncertainty"])
    print("[适用边界] %s" % result["applicability"])


if __name__ == "__main__":
    main()
