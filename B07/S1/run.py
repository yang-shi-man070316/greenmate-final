"""S1 稳态基线：完整执行链路入口。

链路：查看当前环境（B05）→ 读取最近 3 小时历史（B02/B05）→ 模型短时预测（B06，不重训练）
     → 结构化判断（优先生成，LLM 无权修改）→ LLM 自然语言解释（B01 LLM 能力，固定 prompt）
     → 保存运行记录（唯一 run_id）。

用法（项目根目录）：
  python B07/S1/run.py                     # 准备稳态数据 + 执行完整链路
  python B07/S1/run.py --prepare           # 仅准备 B02 稳态数据段
  python B07/S1/run.py --inspect RUN_ID    # 按 run_id 读取本次全部记录并回答问题
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B05.tools import get_current_environment, get_environment_history  # noqa: E402
from B06.predict import predict_latest  # noqa: E402 （加载已保存模型，不重训练）

from judgment import build_judgment  # noqa: E402
from llm_explain import explain  # noqa: E402
from prepare import ensure_stable_window  # noqa: E402
from records import load_run, make_run_id, save_run, summarize  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def run_pipeline():
    """执行完整链路，返回运行记录。"""
    print("[S1] 步骤 0：准备 B02 稳态数据段（29~30℃ 白昼窗口）")
    _, stability = ensure_stable_window()
    print("[S1]   稳定性：%s" % ("稳定 ✅" if stability["stable"] else "不满足 ❌"))

    print("[S1] 步骤 1：查看当前环境（B05 get_current_environment）")
    current = get_current_environment()
    print("[S1]   %s" % json.dumps(current, ensure_ascii=False))

    print("[S1] 步骤 2：读取最近 3 小时历史（B05 get_environment_history(3)）")
    history = get_environment_history(3)
    print("[S1]   status=%s，样本 %s 条" % (history["status"],
          len((history.get("data") or {}).get("samples") or [])))

    print("[S1] 步骤 3：模型短时预测（B06 已保存模型，不重新训练）")
    prediction = predict_latest()
    print("[S1]   predicted_attention=%s | model_version=%s | 概率=%s（模型输出原样保留，不修改）" % (
        prediction["predicted_attention"], prediction["model_version"], prediction["probability"]))

    print("[S1] 步骤 4：生成结构化判断（LLM 无权修改）")
    judgment = build_judgment(current, history, prediction)
    print("[S1]   verdict=%s" % judgment["verdict"])

    print("[S1] 步骤 5：LLM 自然语言解释（B01 LLM 能力，固定 prompt）")
    llm = explain({
        "current_state": judgment["current_state"],
        "recent_trend": judgment["recent_trend"],
        "prediction": {"predicted_attention": prediction["predicted_attention"],
                       "model_version": prediction["model_version"],
                       "probability": prediction["probability"]},
        "judgment": judgment,
    })
    print("[S1]   LLM 状态=%s" % llm.get("status"))

    run_id = make_run_id()
    record = {
        "run_id": run_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "s1_task": "S1 稳态基线",
        "stability_dataset": stability,
        "step1_current_environment": current,
        "step2_recent_history_3h": history,
        "step3_model_prediction": prediction,
        "step4_structured_judgment": judgment,
        "step5_llm_explanation": llm,
        "chain_status": ("complete" if llm.get("status") == "success"
                         else "structured_complete_llm_unavailable"),
    }
    path = save_run(record)
    print("[S1] 运行记录已保存：%s" % path)
    print("[S1] ======== run_id: %s ========" % run_id)
    print("[S1] 查看记录：python B07/S1/run.py --inspect %s" % run_id)
    return record


def main():
    parser = argparse.ArgumentParser(description="GreenMate S1 稳态基线")
    parser.add_argument("--prepare", action="store_true", help="仅准备 B02 稳态数据段")
    parser.add_argument("--inspect", metavar="RUN_ID", help="按 run_id 读取记录并回答问题")
    args = parser.parse_args()

    if args.inspect:
        record = load_run(args.inspect)
        print(summarize(record))
        return 0
    if args.prepare:
        from prepare import main as prepare_main
        return prepare_main()
    run_pipeline()
    return 0


if __name__ == "__main__":
    sys.exit(main())
