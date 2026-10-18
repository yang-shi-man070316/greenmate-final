"""B06 训练 + 评估 + 保存 + 重载。

流程：
1. 构建数据集（窗口 → 8 骨架特征 → 透明规则标签），按时间切分（无泄露）；
2. 类别分布 → 多数类朴素基线（sklearn DummyClassifier）；
3. 传统 ML：RandomForest（random_state 固定，可复现）；
4. 评估：混淆矩阵、F1（macro/weighted）、召回率（classification_report）；
5. 对比基线 vs ML，解释性能变化；
6. 错误样本解释：至少 1 个假阳性 + 1 个假阴性（特征值 + 标签规则 + 可回溯时段）；
7. 保存模型 + 元数据（版本/特征列表/窗口配置/指标），支持完全重启后重载。

运行：python B06/train.py
"""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score, recall_score

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from dataset import TRAIN_END, build_dataset, split_train_test  # noqa: E402
from features import FEATURE_NAMES  # noqa: E402
from labeling import RULE_DESCRIPTIONS  # noqa: E402

MODELS_DIR = ROOT / "models"
MODEL_FILE = MODELS_DIR / "b06_model.joblib"
METADATA_FILE = MODELS_DIR / "model_metadata.json"

CONFIG = {
    "window_size": 6,
    "prediction_horizon": 4,
    "model_version": "b06-rf-v1",
}

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def _metrics(y_true, y_pred):
    cm = confusion_matrix(y_true, y_pred, labels=["NORMAL", "WATCH"])
    report = classification_report(y_true, y_pred, labels=["NORMAL", "WATCH"],
                                   output_dict=True, zero_division=0)
    return {
        "confusion_matrix": {
            "TN": int(cm[0][0]), "FP": int(cm[0][1]),
            "FN": int(cm[1][0]), "TP": int(cm[1][1]),
            "labels": ["NORMAL", "WATCH"],
        },
        "f1_macro": round(report["macro avg"]["f1-score"], 4),
        "f1_weighted": round(report["weighted avg"]["f1-score"], 4),
        "recall_NORMAL": round(report["NORMAL"]["recall"], 4),
        "recall_WATCH": round(report["WATCH"]["recall"], 4),
    }


def _explain_error(kind, idx, rows, y_true, y_pred, model, X):
    """解释一个错误样本：真实/预测标签、标签规则、特征值、模型概率、可回溯时段。"""
    r = rows[idx]
    feats = {f: r[f] for f in FEATURE_NAMES}
    proba = model.predict_proba([X[idx]])[0]
    classes = list(model.classes_)
    prob_map = {c: round(float(p), 3) for c, p in zip(classes, proba)}
    if kind == "FP":  # 实际 NORMAL，预测 WATCH：模型把哪些特征当成了风险信号
        clues = []
        if abs(r["temp_delta"]) > 4:
            clues.append("窗口内温度剧变（temp_delta=%.1f℃）" % r["temp_delta"])
        if abs(r["hum_delta"]) > 15:
            clues.append("窗口内湿度剧变（hum_delta=%.1f%%）" % r["hum_delta"])
        if r["hum_mean"] < 45:
            clues.append("湿度均值偏低（hum_mean=%.1f%%）" % r["hum_mean"])
        if r["temp_mean"] > 28:
            clues.append("温度均值偏高（temp_mean=%.1f℃）" % r["temp_mean"])
        if r["light_mean"] > 30000:
            clues.append("光照均值高（light_mean=%.0f lux，白天属正常）" % r["light_mean"])
        reason = ("；".join(clues) or "特征组合接近 WATCH 边界") + (
            "——扰动/恢复期的快速变化被模型识别为风险信号，但预测窗口实际已回归正常（假警报）")
    else:  # FN：实际 WATCH，预测 NORMAL
        rule = RULE_DESCRIPTIONS.get(r["label_source"].split("+")[0], r["label_source"])
        reason = ("标签由规则触发（%s），但输入窗口结束时湿度仍为 %.1f%%、温度 %.1f℃（%s），"
                  "恶化过程发生在预测窗口内，过去 3 小时的特征不足以让模型提前预警（漏报）" % (
                      rule, r["hum_current"], r["temp_current"],
                      "湿度呈下降趋势" if r["hum_delta"] < 0 else "无明显恶化趋势"))
    return {
        "kind": kind,
        "true_label": y_true[idx],
        "predicted_label": y_pred[idx],
        "label_source": r["label_source"],
        "window": "%s ~ %s（预测窗口 %s ~ %s）" % (
            r["window_start"], r["window_end"], r["predict_start"], r["predict_end"]),
        "features": feats,
        "model_proba": prob_map,
        "explanation": reason,
    }


def train_and_evaluate():
    rows = build_dataset(CONFIG["window_size"], CONFIG["prediction_horizon"])
    train, test, dropped = split_train_test(rows, TRAIN_END)

    X_train = np.array([[r[f] for f in FEATURE_NAMES] for r in train])
    y_train = [r["label"] for r in train]
    X_test = np.array([[r[f] for f in FEATURE_NAMES] for r in test])
    y_test = [r["label"] for r in test]

    dist_train = dict(Counter(y_train))
    dist_test = dict(Counter(y_test))

    # 1. 多数类朴素基线
    dummy = DummyClassifier(strategy="most_frequent")
    dummy.fit(X_train, y_train)
    y_pred_base = dummy.predict(X_test)
    base_metrics = _metrics(y_test, y_pred_base)

    # 2. 传统 ML：RandomForest（固定随机种子，可复现）
    model = RandomForestClassifier(n_estimators=200, max_depth=8,
                                   random_state=42, class_weight="balanced")
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    ml_metrics = _metrics(y_test, y_pred)

    # 3. 错误样本（FP / FN 各至少 1 个）
    errors = []
    for kind, cond in (("FP", lambda t, p: t == "NORMAL" and p == "WATCH"),
                       ("FN", lambda t, p: t == "WATCH" and p == "NORMAL")):
        for i in range(len(test)):
            if cond(y_test[i], y_pred[i]):
                errors.append(_explain_error(kind, i, test, y_test, y_pred, model, X_test))
                break

    # 4. 保存模型 + 元数据
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = {
        "model_version": CONFIG["model_version"],
        "trained_at": trained_at,
        "window_size": CONFIG["window_size"],
        "prediction_horizon": CONFIG["prediction_horizon"],
        "feature_names": FEATURE_NAMES,
        "dataset": {
            "total_windows": len(rows),
            "train_n": len(train), "test_n": len(test), "dropped_cross_boundary": len(dropped),
            "train_end_boundary": TRAIN_END,
            "label_dist_train": dist_train,
            "label_dist_test": dist_test,
        },
        "baseline_majority_class": str(dummy.classes_[0]),
        "baseline_metrics": base_metrics,
        "ml_metrics": ml_metrics,
        "feature_importances": {
            f: round(float(v), 4) for f, v in zip(FEATURE_NAMES, model.feature_importances_)
        },
        "error_samples": errors,
    }
    joblib.dump({"model": model, "metadata": metadata}, MODEL_FILE)
    METADATA_FILE.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def load_model():
    """重载模型并校验版本/窗口定义/特征列表一致性。"""
    bundle = joblib.load(MODEL_FILE)
    m = bundle["metadata"]
    if m["window_size"] != CONFIG["window_size"] or m["prediction_horizon"] != CONFIG["prediction_horizon"]:
        raise ValueError("窗口定义不一致：模型 window_size=%s horizon=%s，当前配置 %s/%s" % (
            m["window_size"], m["prediction_horizon"], CONFIG["window_size"], CONFIG["prediction_horizon"]))
    if m["feature_names"] != FEATURE_NAMES:
        raise ValueError("特征列表不一致：模型特征 %s" % m["feature_names"])
    return bundle["model"], m


def main():
    metadata = train_and_evaluate()
    print("[数据集] 窗口总数 %d | 训练 %d | 测试 %d | 跨边界丢弃 %d" % (
        metadata["dataset"]["total_windows"], metadata["dataset"]["train_n"],
        metadata["dataset"]["test_n"], metadata["dataset"]["dropped_cross_boundary"]))
    print("[标签分布] 训练 %s | 测试 %s" % (
        metadata["dataset"]["label_dist_train"], metadata["dataset"]["label_dist_test"]))
    print("[基线(多数类=%s)] F1_weighted=%.4f 混淆矩阵=%s" % (
        metadata["baseline_majority_class"], metadata["baseline_metrics"]["f1_weighted"],
        metadata["baseline_metrics"]["confusion_matrix"]))
    ml = metadata["ml_metrics"]
    print("[ML RandomForest] F1_macro=%.4f F1_weighted=%.4f recall_NORMAL=%.4f recall_WATCH=%.4f" % (
        ml["f1_macro"], ml["f1_weighted"], ml["recall_NORMAL"], ml["recall_WATCH"]))
    print("[ML 混淆矩阵] %s" % ml["confusion_matrix"])
    print("[特征重要性] %s" % metadata["feature_importances"])
    for e in metadata["error_samples"]:
        print("[%s 错误样本] 真实=%s 预测=%s 规则=%s 时段=%s" % (
            e["kind"], e["true_label"], e["predicted_label"], e["label_source"] or "无", e["window"]))
        print("    解释: %s" % e["explanation"])
    print("[已保存] %s（version=%s, trained_at=%s）" % (MODEL_FILE, metadata["model_version"], metadata["trained_at"]))

    # 重载验证
    model2, m2 = load_model()
    X_test2 = np.array([[r[f] for f in FEATURE_NAMES] for r in build_dataset(CONFIG["window_size"], CONFIG["prediction_horizon"])])
    print("[重载验证] 模型版本 %s，重载后特征/窗口定义校验通过" % m2["model_version"])
    return metadata


if __name__ == "__main__":
    main()
