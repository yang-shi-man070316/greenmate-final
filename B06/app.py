"""B06 FastAPI 子应用：机器学习闭环（挂载于 /B06，见 run.py）。

API：
- GET  /api/overview   数据集概览（窗口数、切分、特征列表、标签分布）
- POST /api/train      训练 + 评估 + 保存（朴素基线 vs ML、混淆矩阵、错误样本）
- GET  /api/model      当前模型元数据（版本/特征/窗口配置/评估指标）
- POST /api/predict    最新窗口推理（predicted_attention + MODEL_OUTPUT）
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dataset import TRAIN_END, build_dataset, split_train_test
from features import FEATURE_NAMES
from predict import predict_latest
from train import CONFIG, METADATA_FILE, train_and_evaluate

STATIC_DIR = Path(__file__).resolve().parent / "static"

b06_app = FastAPI(title="GreenMate B06 — 机器学习闭环")


@b06_app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@b06_app.get("/api/overview")
def overview():
    rows = build_dataset(CONFIG["window_size"], CONFIG["prediction_horizon"])
    train, test, dropped = split_train_test(rows, TRAIN_END)
    from collections import Counter
    return {
        "window_config": {"window_size": CONFIG["window_size"],
                          "prediction_horizon": CONFIG["prediction_horizon"]},
        "feature_names": FEATURE_NAMES,
        "total_windows": len(rows),
        "train_n": len(train),
        "test_n": len(test),
        "dropped_cross_boundary": len(dropped),
        "train_end_boundary": TRAIN_END,
        "label_dist": dict(Counter(r["label"] for r in rows)),
        "note": "特征仅 8 个骨架（current/mean/delta）；sim_scenario、label_source、B03 天气均不进入特征",
    }


@b06_app.post("/api/train")
def train():
    """训练+评估+保存（同步执行，约数秒）。"""
    metadata = train_and_evaluate()
    return metadata


@b06_app.get("/api/model")
def model_info():
    if not METADATA_FILE.exists():
        return {"available": False, "message": "尚未训练，请先 POST /B06/api/train"}
    import json
    return {"available": True, **json.loads(METADATA_FILE.read_text(encoding="utf-8"))}


@b06_app.post("/api/predict")
def predict():
    return predict_latest()


b06_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="b06_static")
