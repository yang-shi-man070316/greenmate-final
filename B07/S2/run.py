"""S2 渐进漂移对照实验入口（风格/输出格式/参数体系对齐 B07/S1/run.py）。

完整执行链路（复用 S1 已跑通的组件，禁止重写）：
步骤0 准备漂移数据（25→30℃ 匀速升温，仅修改 B02 历史时序数据）
  → 步骤1 当前环境（B05）→ 步骤2 最近3小时历史（B05）
  → 步骤3 B06 模型预测（不重训）→ 步骤4 结构化判定（S1 判断引擎，LLM 无权修改）
  → 步骤5 LLM 自然语言解释（固定 prompt，与 S1 完全一致，无人工提示）
  → 保存运行记录（唯一 run_id，s2- 前缀）

用法（项目根目录）：
  python B07/S2/run.py                     # 执行完整链路（漂移场景）
  python B07/S2/run.py --prepare           # 仅准备漂移数据段
  python B07/S2/run.py --inspect RUN_ID    # 按 run_id 读取本次全部记录并回答问题
"""

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B05.tools import get_current_environment, get_environment_history  # noqa: E402
from B06.predict import predict_latest  # noqa: E402
from B07.S1.judgment import build_judgment  # noqa: E402
from B07.S1.llm_explain import explain  # noqa: E402

from drift_inject import inject_drift  # noqa: E402

S2_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S2_DIR / "run_records"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    """run_id 格式：s2-年月日时分秒-6位短uuid（如 s2-20261020223000-8f2ac7）。"""
    return "s2-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


def save_run(record):
    """自动新建 run_records 目录，记录文件名与 run_id 对应。"""
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    path = RECORDS_DIR / ("%s.json" % record["run_id"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_run(run_id):
    if not re.match(r"^[A-Za-z0-9_-]+$", run_id or ""):
        raise ValueError("非法 run_id：%s" % run_id)
    path = RECORDS_DIR / ("%s.json" % run_id)
    if not path.exists():
        raise FileNotFoundError("未找到运行记录：%s（run_records 目录：%s）" % (run_id, RECORDS_DIR))
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(record):
    """用运行记录回答两个问题（对齐 S1 的 inspect 风格）。"""
    judgment = record.get("step4_structured_judgment", {})
    trend = judgment.get("recent_trend", {})
    prediction = record.get("step3_model_prediction", {})
    current = record.get("step1_current_environment", {})
    llm = record.get("step5_llm_explanation", {})

    lines = [
        "=" * 64,
        "运行记录 %s（创建于 %s）" % (record.get("run_id"), record.get("created_at")),
        "=" * 64,
        "",
        "【Q1 这次 GreenMate 看到了什么？】",
        "  1) 当前环境（B05 get_current_environment，SIMULATED）：%s" % (
            (current.get("data") or {}) if isinstance(current, dict) else current),
        "  2) 最近 3 小时历史（B02 SQLite，%s 条）：%s" % (
            trend.get("count", "?"), trend.get("window", "无")),
    ]
    if trend.get("available"):
        lines.append(
            "     温度 min=%.1f max=%.1f mean=%.1f（首点 %.1f → 末点 %.1f） | 湿度 min=%.1f max=%.1f"
            % (trend["temperature"]["min"], trend["temperature"]["max"], trend["temperature"]["mean"],
               record["step2_recent_history_3h"]["data"]["samples"][0]["temperature"],
               record["step2_recent_history_3h"]["data"]["samples"][-1]["temperature"],
               trend["humidity"]["min"], trend["humidity"]["max"]))
    lines += [
        "  3) 模型短时预测（B06，版本 %s）：predicted_attention=%s，概率 %s" % (
            prediction.get("model_version"), prediction.get("predicted_attention"),
            prediction.get("probability")),
        "  4) 结构化判断：verdict=%s（LLM 无权修改）" % judgment.get("verdict"),
        "",
        "【Q2 最后为什么说需要重点关注（识别升温漂移）？】",
    ]
    if trend.get("available"):
        t, h = trend["temperature"], trend["humidity"]
        lines.append(
            "  近 3 小时温度从 %.1f℃ 匀速渐进升温至 %.1f℃（幅差 %s℃），"
            "前后半均值差 %+.2f℃/窗口（持续上升漂移，远超稳定阈值 0.5℃）；"
            "湿度 %s~%s%%；结构化判断 verdict=%s → 关注等级：需要重点关注。" % (
                record["step2_recent_history_3h"]["data"]["samples"][0]["temperature"],
                record["step2_recent_history_3h"]["data"]["samples"][-1]["temperature"],
                round(t["max"] - t["min"], 1), t["half_diff"],
                h["min"], h["max"], judgment.get("verdict")))
    else:
        lines.append("  历史数据缺失，无趋势结论（inconclusive）")
    if llm.get("status") == "success":
        lines += ["", "【LLM 自然语言解释（固定 prompt）】", llm["answer"]]
    else:
        lines += ["", "【LLM 解释】不可用：[%s] %s（结构化判断不受影响）" % (
            llm.get("error_type"), llm.get("message"))]
    return "\n".join(lines)


def run_pipeline():
    """执行 S2 漂移场景完整链路，返回运行记录。"""
    print("[S2] 步骤 0：准备漂移数据段（25→30℃ 匀速升温，仅修改 B02 历史时序数据）")
    inject_drift()

    print("[S2] 步骤 1：查看当前环境（B05 get_current_environment）")
    current = get_current_environment()
    print("[S2]   %s" % json.dumps(current, ensure_ascii=False))

    print("[S2] 步骤 2：读取最近 3 小时历史（B05 get_environment_history(3)）")
    history = get_environment_history(3)
    samples = (history.get("data") or {}).get("samples") or []
    if samples:
        temps = [p["temperature"] for p in samples]
        print("[S2]   status=%s，样本 %s 条，温度 %.1f → %.1f℃" % (
            history["status"], len(samples), temps[0], temps[-1]))
    else:
        print("[S2]   status=%s，无样本" % history.get("status"))

    print("[S2] 步骤 3：模型短时预测（B06 已保存模型，不重新训练）")
    prediction = predict_latest()
    print("[S2]   predicted_attention=%s | model_version=%s | 概率=%s（模型输出原样保留，不修改）" % (
        prediction["predicted_attention"], prediction["model_version"], prediction["probability"]))

    print("[S2] 步骤 4：生成结构化判断（复用 S1 判断引擎，LLM 无权修改）")
    judgment = build_judgment(current, history, prediction)
    print("[S2]   verdict=%s" % judgment["verdict"])

    print("[S2] 步骤 5：LLM 自然语言解释（B01 LLM 能力，固定 prompt 与 S1 完全一致，无人工提示）")
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
    path = save_run(record)
    print("[S2] 运行记录已保存：%s" % path)
    print("[S2] ======== run_id: %s ========" % run_id)
    print("[S2] 查看记录：python B07/S2/run.py --inspect %s" % run_id)
    return record


def main():
    parser = argparse.ArgumentParser(description="GreenMate S2 渐进漂移对照实验")
    parser.add_argument("--prepare", action="store_true", help="仅准备漂移数据段")
    parser.add_argument("--inspect", metavar="RUN_ID", help="按 run_id 读取记录并回答问题")
    args = parser.parse_args()

    if args.inspect:
        record = load_run(args.inspect)
        print(summarize(record))
        return 0
    if args.prepare:
        inject_drift()
        return 0
    run_pipeline()
    return 0


if __name__ == "__main__":
    sys.exit(main())
