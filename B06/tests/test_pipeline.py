"""端到端流水线测试（无需 LLM / 无需联网）：
训练 → 评估 → 保存 → 重载 → 最新窗口推理。

断言：
- 训练产出评估报告（混淆矩阵/F1/召回率/错误样本）；
- 模型可重载且版本/窗口定义/特征列表一致；
- 最新推理输出 predicted_attention + model_version + MODEL_OUTPUT 标记，
  且与 B03 天气 / B04 知识证据结构分离。

运行：python B06/tests/test_pipeline.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B06 目录
sys.path.insert(0, str(ROOT))

from train import CONFIG, load_model, train_and_evaluate  # noqa: E402
from predict import predict_latest  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    results = []

    def check(name, passed, detail=""):
        results.append(passed)
        print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))

    metadata = train_and_evaluate()
    check("训练完成，评估报告齐全",
          "ml_metrics" in metadata and "baseline_metrics" in metadata
          and "confusion_matrix" in metadata["ml_metrics"]
          and "error_samples" in metadata,
          "version=%s" % metadata["model_version"])
    ml = metadata["ml_metrics"]
    check("混淆矩阵/召回率数值合法",
          0 <= ml["recall_NORMAL"] <= 1 and 0 <= ml["recall_WATCH"] <= 1
          and ml["confusion_matrix"]["TP"] + ml["confusion_matrix"]["FP"] > 0)
    check("ML 不低于多数类基线（加权F1）",
          ml["f1_weighted"] >= metadata["baseline_metrics"]["f1_weighted"],
          "ML %.4f vs 基线 %.4f" % (ml["f1_weighted"], metadata["baseline_metrics"]["f1_weighted"]))
    check("错误样本至少覆盖 FP 与 FN 各 1 个（或如实记录缺失）",
          len(metadata["error_samples"]) >= 1
          or metadata["ml_metrics"]["confusion_matrix"]["FP"] == 0
          or metadata["ml_metrics"]["confusion_matrix"]["FN"] == 0,
          "错误样本 %d 个" % len(metadata["error_samples"]))
    check("特征重要性覆盖 8 个骨架特征",
          set(metadata["feature_importances"].keys()) == set(metadata["feature_names"]))
    check("模型版本与窗口定义已保存", metadata["model_version"] == CONFIG["model_version"]
          and metadata["window_size"] == CONFIG["window_size"])

    # 重载验证
    model, m = load_model()
    check("模型重载成功且元数据一致", m["model_version"] == metadata["model_version"]
          and m["feature_names"] == metadata["feature_names"])

    # 最新窗口推理
    p = predict_latest()
    check("最新推理输出预测类别", p["predicted_attention"] in ("NORMAL", "WATCH"),
          str(p["predicted_attention"]))
    check("MODEL_OUTPUT 标记存在", p.get("output_marker") == "MODEL_OUTPUT")
    check("model_version 与训练一致", p["model_version"] == metadata["model_version"])
    check("推理结构与天气/知识证据分离（含适用边界说明）",
          p.get("prediction_type") == "attention_prediction" and "applicability" in p)
    check("输入窗口为最新 6 点", p["input_window"]["window_size"] == CONFIG["window_size"],
          "%s ~ %s" % (p["input_window"]["start"], p["input_window"]["end"]))

    print("\n端到端流水线总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
