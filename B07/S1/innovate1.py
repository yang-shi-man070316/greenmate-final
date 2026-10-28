"""GreenMate B07 创新点1 对照验证实验：看懂时序状态演化推理机制。

验证逻辑（拿掉 → 恢复 → 比较 → 追踪）：
选用 S2 数据集（B02 库尾漂移段：25→30℃ 匀速升温，当前温度约 30℃），
三组固定对照运行，统一提问完全一致：

  run_current_only            仅当前观测（温度/湿度/光照），无历史时序、无短时预测
  run_with_history            当前观测 + B02 最近 3 小时历史时序（关闭预测）
  run_with_history_prediction 当前观测 + 历史时序 + B06 短时预测（完整证据链）

硬性区分：历史时序 = 已发生的变化趋势；B06 输出 = 下一窗口短时预测。
复用 S1/S2/B02/B06 已有机制，不新增核心模块，无前端页面。

用法（项目根目录）：
  python B07/S1/innovate1.py --run-all                       # 依次运行三组 + 生成报告
  python B07/S1/innovate1.py --run current_only|with_history|with_history_prediction
  python B07/S1/innovate1.py --report                        # 生成 INNOVATE_1_REPORT.md
  python B07/S1/innovate1.py --inspect RUN_ID                # 读取记录
"""

import argparse
import json
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

import numpy as np  # noqa: E402
from openai import OpenAI  # noqa: E402

from B02 import db as b02_db  # noqa: E402
from B06.features import extract_features, feature_vector  # noqa: E402
from B06.train import load_model  # noqa: E402
from B07.S1.judgment import trend_of  # noqa: E402
from llm import LLMError, get_config, map_error  # noqa: E402

S1_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S1_DIR / "run_records"

FIXED_QUESTION = "结合全部可用证据，分析当前番茄生长环境风险：哪些方面可以判断，哪些方面因证据受限无法判断？"

MODES = ("run_current_only", "run_with_history", "run_with_history_prediction")

SYSTEM_PROMPT = (
    "你是 GreenMate 环境分析助手。回答必须严格分为两块：\n"
    "【可判断内容】基于可用证据进行推理并给出判断，每条判断说明依据；\n"
    "【受限说明】清晰写明哪些证据缺失、哪些判断因此不可靠，禁止编造缺失数据。\n"
    "重要区分（禁止混为一谈）：\n"
    "- 历史时序（B02）描述的是【已经发生】的变化趋势；\n"
    "- 短时预测（B06）输出的是【下一窗口】的预测，不是已发生事实；\n"
    "- 引用趋势时说明『已发生』，引用预测时说明『预测/预计』。\n"
    "禁止输出『一定、必然、肯定』等强确定性结论。用中文回答，简洁。"
)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    return "i1-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


def save_run(record):
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


# ---------------- 数据装载（复用 S2 漂移段 + B02 + B06） ----------------

def load_drift_window():
    """读取 B02 库尾漂移段（S2 数据：25→30℃ 匀速升温），返回 (7点历史, 当前点, 6点预测窗口)。"""
    conn = b02_db.connect()
    try:
        rows = b02_db.query_series(conn)
    finally:
        conn.close()
    tail = rows[-7:]
    temps = [r["temperature"] for r in tail]
    if not (abs(temps[0] - 25.0) < 0.5 and abs(temps[-1] - 30.0) < 0.5
            and temps[-1] - temps[0] >= 4.0):
        raise RuntimeError("B02 库尾不是 S2 漂移段（25→30℃ 升温）。请先运行 python B07/S2/run.py --prepare")
    current_point = tail[-1]
    return tail, current_point, tail[-6:]


def load_prediction():
    """B06 已训模型对漂移段最新 6 点的短时预测（不重训）。"""
    model, metadata = load_model()
    _, _, points = load_drift_window()
    vec = feature_vector(extract_features(points))
    proba = model.predict_proba([vec])[0]
    classes = list(model.classes_)
    return {
        "predicted_attention": classes[int(np.argmax(proba))],
        "model_version": metadata["model_version"],
        "probability": {c: round(float(p), 4) for c, p in zip(classes, proba)},
        "input_window": "%s ~ %s" % (points[0]["timestamp"], points[-1]["timestamp"]),
    }


# ---------------- 判定（透明规则，区分趋势与预测） ----------------

def judge(mode, current_point, history_samples, prediction):
    """三组判定。历史=已发生趋势；预测=下一窗口。"""
    if mode == "run_current_only":
        return {
            "verdict": "current_only_limited",
            "verdict_note": ("仅有当前瞬时值：温度 %.1f℃ 处于高温胁迫边界（≥30℃），"
                             "只能做静态判断，无法判断演化方向（无历史、无预测）"
                             % current_point["temperature"]),
        }
    trend = trend_of(history_samples)
    if mode == "run_with_history":
        verdict = "attention_trend" if not trend.get("data_stable") else "stable_trend"
        return {
            "verdict": verdict,
            "verdict_note": ("历史时序显示已发生的持续升温（%.1f → %.1f℃，前后半均值差 %+.2f℃），"
                             "趋势是已发生事实；无短时预测，无法讨论下一窗口"
                             % (history_samples[0]["temperature"], history_samples[-1]["temperature"],
                                trend["temperature"]["half_diff"])),
            "trend": trend,
        }
    # run_with_history_prediction
    pred = (prediction or {}).get("predicted_attention")
    if not trend.get("data_stable"):
        if pred == "WATCH":
            verdict = "attention_trend_prediction_watch"
            note = "已发生的升温趋势 + 下一窗口预测 WATCH（风险预计延续）"
        else:
            verdict = "attention_trend_prediction_normal"
            note = ("已发生的升温趋势（风险）+ 下一窗口预测 NORMAL（预计缓解/稳定）："
                    "趋势与预测指向不同，必须区分引用")
    else:
        verdict = "stable_trend_prediction_%s" % (pred or "none")
        note = "历史趋势稳定 + 下一窗口预测 %s" % pred
    return {"verdict": verdict, "verdict_note": note, "trend": trend}


# ---------------- LLM（复用 B01 能力，统一固定提问） ----------------

def explain(mode, current_point, history_samples, prediction, judgment):
    try:
        api_key, base_url, model, timeout = get_config()
    except LLMError as e:
        return {"status": "error", "error_type": e.error_type, "message": e.message}

    hist_text = "（未提供历史时序）"
    if history_samples:
        t = judgment.get("trend") or trend_of(history_samples)
        hist_text = ("近 3 小时 %s ~ %s，共 %d 点：温度 %.1f → %.1f℃（已发生的趋势，"
                     "幅差 %.1f℃，前后半均值差 %+.2f℃/窗口，data_stable=%s）" % (
                         history_samples[0]["timestamp"], history_samples[-1]["timestamp"],
                         len(history_samples),
                         history_samples[0]["temperature"], history_samples[-1]["temperature"],
                         round(t["temperature"]["max"] - t["temperature"]["min"], 1),
                         t["temperature"]["half_diff"], t.get("data_stable")))
    pred_text = "（未提供短时预测）"
    if prediction:
        pred_text = ("B06 下一窗口短时预测：predicted_attention=%s，概率=%s（model_version=%s，"
                     "这是预测，不是已发生事实）" % (
                         prediction["predicted_attention"], prediction["probability"],
                         prediction["model_version"]))

    user_message = (
        "%s\n\n"
        "当前观测：温度 %.1f℃，湿度 %.1f%%，光照 %.0f lux（SIMULATED）\n"
        "历史时序：%s\n"
        "短时预测：%s\n"
        "系统判定：verdict=%s（%s）\n"
        "请按两块式规则输出，严格区分趋势与预测。"
    ) % (FIXED_QUESTION,
         current_point["temperature"], current_point["humidity"], current_point["light"],
         hist_text, pred_text, judgment["verdict"], judgment["verdict_note"])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        answer = (resp.choices[0].message.content or "").strip()
        return {"status": "success", "answer": answer, "model": model,
                "has_judgable_section": "可判断内容" in answer,
                "has_limitation_section": "受限说明" in answer,
                "elapsed_ms": round((time.time() - started) * 1000)}
    except Exception as e:
        err = map_error(e, base_url, timeout, round((time.time() - started) * 1000))
        err["status"] = "error"
        return err


def run_pipeline(mode):
    print("[I1:%s] 组装证据链（拿掉 → 恢复 → 比较）" % mode)
    history, current_point, _ = load_drift_window()
    history_samples = history if mode != "run_current_only" else None
    prediction = load_prediction() if mode == "run_with_history_prediction" else None
    print("[I1:%s]   当前观测：%.1f℃/%.1f%%/%.0f lux | 历史：%s | 预测：%s" % (
        mode, current_point["temperature"], current_point["humidity"], current_point["light"],
        "%d 点（25→30℃ 漂移段）" % len(history) if history_samples else "无",
        prediction["predicted_attention"] if prediction else "无"))

    print("[I1:%s] 判定（区分趋势与预测）" % mode)
    judgment = judge(mode, current_point, history_samples or [], prediction)
    print("[I1:%s]   verdict=%s（%s）" % (mode, judgment["verdict"], judgment["verdict_note"]))

    print("[I1:%s] LLM 两块式推理（统一固定提问）" % mode)
    llm = explain(mode, current_point, history_samples or [], prediction, judgment)
    print("[I1:%s]   LLM 状态=%s | 含「可判断内容」=%s | 含「受限说明」=%s" % (
        mode, llm.get("status"), llm.get("has_judgable_section"),
        llm.get("has_limitation_section")))

    run_id = make_run_id()
    record = {
        "run_id": run_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "innovate1_task": "创新点1 时序状态演化对照验证",
        "experiment": "innovate1",
        "mode": mode,
        "fixed_question": FIXED_QUESTION,
        "current_observation": {k: current_point[k] for k in
                                ("timestamp", "temperature", "humidity", "light")},
        "history_samples": history_samples,
        "prediction": prediction,
        "judgment": judgment,
        "llm_explanation": llm,
        "chain_status": ("complete" if llm.get("status") == "success"
                         else "structured_complete_llm_unavailable"),
    }
    path = save_run(record)
    print("[I1:%s] 运行记录已保存：%s" % (mode, path))
    print("[I1:%s] ======== run_id: %s ========" % (mode, run_id))
    return record


# ---------------- 报告 ----------------

def find_latest_by_mode(mode):
    files = sorted(RECORDS_DIR.glob("i1-*.json"))
    for path in reversed(files):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("mode") == mode:
            return record
    return None


def _answer_three_questions(r1, r2, r3):
    """报告末尾三个问题：从三组记录归纳答案。"""
    q1 = ("只看当前值：只能做静态判断——%.1f℃ 处于高温胁迫边界（≥30℃），"
          "可以提醒防高温；但不知道温度是稳定在 30℃、还是刚从 25℃ 升上来、"
          "还是即将回落，无法判断演化方向（verdict=%s）。" % (
              r1["current_observation"]["temperature"], r1["judgment"]["verdict"]))
    t2 = r2["judgment"].get("trend") or {}
    q2 = ("加入历史后：多知道了『已发生的变化过程』——温度在近 3 小时从 25℃ 持续升温到 30℃"
          "（前后半均值差 %+.2f℃/窗口，data_stable=%s），同样的 30℃ 被识别为"
          "『持续升温到达的风险状态』而非稳态（verdict=%s）。" % (
              t2.get("temperature", {}).get("half_diff", "?"),
              t2.get("data_stable"), r2["judgment"]["verdict"]))
    q3 = ("加入短时预测后：可以多讨论『下一窗口』的走向——B06 预测 %s（概率 %s），"
          "这是预测而非已发生事实；趋势与预测可能一致也可能分歧"
          "（本次：趋势升温 vs 预测 %s，verdict=%s），"
          "风险讨论从『已经怎样』延伸到『接下来可能怎样』。" % (
              r3["prediction"]["predicted_attention"], r3["prediction"]["probability"],
              r3["prediction"]["predicted_attention"], r3["judgment"]["verdict"]))
    return q1, q2, q3


def generate_report():
    records = {}
    for mode in MODES:
        records[mode] = find_latest_by_mode(mode)
        if not records[mode]:
            print("缺少 %s 的运行记录，请先运行 --run-all 或逐个 --run" % mode)
            return 1
    r1, r2, r3 = (records[m] for m in MODES)
    q1, q2, q3 = _answer_three_questions(r1, r2, r3)

    def cell(mode):
        r = records[mode]
        return "%s<br>%s" % (r["judgment"]["verdict"], r["judgment"]["verdict_note"])

    lines = [
        "# GreenMate B07 创新点1 对照验证实验报告：时序状态演化推理机制",
        "",
        "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 实验方法：拿掉 → 恢复 → 比较 → 追踪（三组固定对照，统一提问）",
        "- 统一固定提问：%s" % FIXED_QUESTION,
        "- 数据：S2 数据集（B02 漂移段，25→30℃ 匀速升温，当前温度约 30℃）",
        "- 三组 run_id：`%s`（current_only）| `%s`（with_history）| `%s`（full）" % (
            r1["run_id"], r2["run_id"], r3["run_id"]),
        "",
        "## 三组对比表",
        "",
        "| 组 | 证据链 | verdict | 可判断内容 | 受限说明 |",
        "| --- | --- | --- | --- | --- |",
        "| run_current_only | 仅当前观测 | %s | %s | %s |" % (
            r1["judgment"]["verdict"],
            (r1["llm_explanation"].get("answer") or "—").split("【受限说明】")[0][:120].replace("\n", " "),
            (r1["llm_explanation"].get("answer") or "—").split("【受限说明】")[-1][:120].replace("\n", " ")),
        "| run_with_history | 当前 + 3h 历史（无预测） | %s | %s | %s |" % (
            r2["judgment"]["verdict"],
            (r2["llm_explanation"].get("answer") or "—").split("【受限说明】")[0][:120].replace("\n", " "),
            (r2["llm_explanation"].get("answer") or "—").split("【受限说明】")[-1][:120].replace("\n", " ")),
        "| run_with_history_prediction | 当前 + 历史 + B06 预测 | %s | %s | %s |" % (
            r3["judgment"]["verdict"],
            (r3["llm_explanation"].get("answer") or "—").split("【受限说明】")[0][:120].replace("\n", " "),
            (r3["llm_explanation"].get("answer") or "—").split("【受限说明】")[-1][:120].replace("\n", " ")),
        "",
        "## 三组 verdict 对照",
        "",
        "| 组 | verdict | 说明 |",
        "| --- | --- | --- |",
        "| 1 | %s | %s |" % (r1["judgment"]["verdict"], r1["judgment"]["verdict_note"]),
        "| 2 | %s | %s |" % (r2["judgment"]["verdict"], r2["judgment"]["verdict_note"]),
        "| 3 | %s | %s |" % (r3["judgment"]["verdict"], r3["judgment"]["verdict_note"]),
        "",
        "## 三个问题",
        "",
        "### 1. 只看当前值，我能判断什么？",
        q1,
        "",
        "### 2. 加入历史后，我又多知道了什么？",
        q2,
        "",
        "### 3. 加入短时预测后，我又能够多讨论什么？",
        q3,
        "",
        "## 创新点1 核心结论",
        "",
        "同样的瞬时数值（30℃），**加入时序之后系统才能区分它是稳定稳态、还是持续升温到达的风险状态**：",
        "- 只看当前值：30℃ 只是『高温边界上的一个点』，无法区分演化过程；",
        "- 加入历史：识别出『已发生的 25→30℃ 持续升温』，同样的 30℃ 被判定为风险状态（attention_trend）；",
        "- 加入预测：风险讨论延伸到『下一窗口预计怎样』（趋势与预测区分引用，可能一致也可能分歧）。",
        "",
        "GreenMate 不是简单拿当前温度直接输出判断，而是走完整分析链路：",
        "",
        "**当前观测 → 历史过程 → 变化趋势 → 短时预测**",
        "",
        "## 三组 LLM 输出原文（追踪）",
        "",
    ]
    for mode in MODES:
        r = records[mode]
        lines += ["### %s（%s，run_id: %s）" % (mode, r["judgment"]["verdict"], r["run_id"]), ""]
        lines.append(r["llm_explanation"].get("answer") or "（LLM 不可用）")
        lines.append("")
    out = S1_DIR / "INNOVATE_1_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("创新点1 对照验证报告已生成：%s" % out)
    return 0


def summarize(record):
    j = record["judgment"]
    lines = [
        "=" * 64,
        "运行记录 %s（%s）" % (record["run_id"], record["mode"]),
        "=" * 64,
        "当前观测：%s" % json.dumps(record["current_observation"], ensure_ascii=False),
        "历史时序：%s" % ("%d 点（%.1f→%.1f℃）" % (
            len(record["history_samples"]), record["history_samples"][0]["temperature"],
            record["history_samples"][-1]["temperature"]) if record["history_samples"] else "无"),
        "短时预测：%s" % (json.dumps(record["prediction"], ensure_ascii=False)
                        if record["prediction"] else "无"),
        "判定：verdict=%s（%s）" % (j["verdict"], j["verdict_note"]),
    ]
    llm = record["llm_explanation"]
    if llm.get("status") == "success":
        lines += ["", "【LLM 两块式输出】", llm["answer"]]
    else:
        lines += ["", "【LLM】不可用：[%s] %s" % (llm.get("error_type"), llm.get("message"))]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="GreenMate B07 创新点1 对照验证实验")
    parser.add_argument("--run-all", action="store_true", help="依次运行三组并生成报告")
    parser.add_argument("--run", choices=MODES, help="运行单组")
    parser.add_argument("--report", action="store_true", help="生成 INNOVATE_1_REPORT.md")
    parser.add_argument("--inspect", metavar="RUN_ID", help="按 run_id 读取记录")
    args = parser.parse_args()

    if args.inspect:
        print(summarize(load_run(args.inspect)))
        return 0
    if args.report:
        return generate_report()
    if args.run:
        run_pipeline(args.run)
        return 0
    if args.run_all:
        for mode in MODES:
            run_pipeline(mode)
            print()
        return generate_report()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
