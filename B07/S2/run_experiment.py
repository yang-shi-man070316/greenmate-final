"""S2 漂移场景完整链路：完全复用 S1 已跑通的链路组件（禁止重写、禁止改模块逻辑）。

复用清单：
- B02 时序数据（本次实验仅注入漂移段数据，见 drift_inject.py）
- B05 工具：get_current_environment / get_environment_history
- B06 预测模型：predict_latest（已训练模型，不重训）
- B07/S1 结构化判断：judgment.build_judgment
- B07/S1 LLM 解释：llm_explain.explain（固定 prompt 与 S1 完全一致，无任何额外提示）
- B07/S1 运行记录：records（唯一 run_id）

天气源、知识库、提示词、模型参数全部固定不变——差异只可能来自 B02 时序历史。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B05.tools import get_current_environment, get_environment_history  # noqa: E402
from B06.predict import predict_latest  # noqa: E402
from B07.S1.judgment import build_judgment  # noqa: E402
from B07.S1.llm_explain import explain  # noqa: E402
from B07.S1.records import make_run_id, save_run  # noqa: E402

from drift_inject import inject_drift  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def run():
    print("[S2] 步骤 0：注入漂移段（仅修改 B02 历史时序数据）")
    inject_drift()

    print("[S2] 步骤 1：查看当前环境（B05，与 S1 同一接口）")
    current = get_current_environment()
    print("[S2]   当前瞬时：%.1f℃ / %.1f%% / %.0f lux（SIMULATED）" % (
        current["data"]["temperature"], current["data"]["humidity"], current["data"]["light"]))

    print("[S2] 步骤 2：读取最近 3 小时历史（B05，系统自主识别趋势，无人工提示）")
    history = get_environment_history(3)
    samples = (history.get("data") or {}).get("samples") or []
    if samples:
        temps = [p["temperature"] for p in samples]
        print("[S2]   %s 条样本：温度 %.1f → %.1f℃" % (
            len(samples), temps[0], temps[-1]))

    print("[S2] 步骤 3：模型短时预测（B06，与 S1 同一模型同一配置）")
    prediction = predict_latest()
    print("[S2]   predicted_attention=%s | model_version=%s | 概率=%s" % (
        prediction["predicted_attention"], prediction["model_version"], prediction["probability"]))

    print("[S2] 步骤 4：结构化判断（复用 S1 判断引擎）")
    judgment = build_judgment(current, history, prediction)
    print("[S2]   verdict=%s" % judgment["verdict"])

    print("[S2] 步骤 5：LLM 解释（固定 prompt 与 S1 完全一致）")
    llm = explain({
        "current_state": judgment["current_state"],
        "recent_trend": judgment["recent_trend"],
        "prediction": {"predicted_attention": prediction["predicted_attention"],
                       "model_version": prediction["model_version"],
                       "probability": prediction["probability"]},
        "judgment": judgment,
    })
    print("[S2]   LLM 状态=%s" % llm.get("status"))

    run_id = make_run_id()
    record = {
        "run_id": run_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "s2_task": "S2 渐进漂移对照实验 - 漂移场景",
        "experiment": "S2_drift",
        "step1_current_environment": current,
        "step2_recent_history_3h": history,
        "step3_model_prediction": prediction,
        "step4_structured_judgment": judgment,
        "step5_llm_explanation": llm,
        "chain_status": ("complete" if llm.get("status") == "success"
                         else "structured_complete_llm_unavailable"),
    }
    path = save_run(record)  # 复用 S1 记录逻辑（共享运行日志库）
    # 交付要求：S2 记录同时镜像到 B07/S2/run_records/
    import shutil
    s2_records_dir = Path(__file__).resolve().parent / "run_records"
    s2_records_dir.mkdir(parents=True, exist_ok=True)
    mirrored = shutil.copy2(path, s2_records_dir / path.name)
    print("[S2] 运行记录已保存：%s" % path)
    print("[S2] 已镜像至 S2 目录：%s" % mirrored)
    print("[S2] ======== run_id: %s ========" % run_id)
    return record


def main():
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
