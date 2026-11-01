"""模块1：证据可信度打分（独立后置分析工具，只读原始文件、不覆盖旧数据）。

四类证据分别输出 0~1 单项可信度，加权综合（权重：时序 0.5、天气 0.3、知识库 0.2，
模型单项分单独输出不参与加权——按任务书权重口径）。
- 时序证据：离群跳变、数值越界、有效历史点不足 7 个 → 降分；
- 天气证据：调用失败、超时、字段缺失 → 单项可信度 = 0；
- 知识库证据：citation 缺失、匹配度低 → 降分；
- 快照完整性：字段缺失、文件损坏 → 降分。

区分语义：该场景无某类证据 → 单项为 null（综合权重归一化剔除）；
证据存在但失效 → 单项为 0（参与加权）——「没有」与「坏了」不是一回事。

输出字段：evidence_score（各单项）、confidence_total、confidence_note。
置信提示文案：≥0.8 证据充足参考价值高；0.4~0.8 证据存在瑕疵仅供参考；
＜0.4 证据质量差建议复核数据源。

用法（项目根目录）：
  python B08/innovate/score/evidence_score.py --file <json>
  python B08/innovate/score/evidence_score.py --dir <目录>     # 批量（只读，结果打印）
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
for d in (ROOT / "B08", ROOT / "B07" / "S5", ROOT / "B07" / "S4", ROOT / "B07" / "S3",
          ROOT / "B07" / "S2", ROOT / "B07" / "S1", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

WEIGHTS = {"history": 0.5, "weather": 0.3, "knowledge": 0.2}
BOUNDS = {"temperature": (0, 50), "humidity": (0, 100), "light": (0, 120000)}

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


# ---------------- 证据提取（兼容 B01~B08 存档结构） ----------------

def extract_evidence(record):
    """从记录提取四类证据与历史逐点序列（只读）。"""
    adopted = record.get("adopted_evidence") or record.get("evidence") or []
    def find(st):
        return next((e for e in adopted if e.get("source_type") == st), None)

    history_ev = find("internal_history")
    weather_ev = find("external_weather") or record.get("weather_forecast")
    knowledge_ev = find("local_knowledge")
    model_ev = find("ml_prediction")
    # B08 v8 验证记录兼容：证据在专属字段（weather_evidence/knowledge_evidence/model_evidence）
    if weather_ev is None and record.get("weather_evidence") is not None:
        weather_ev = record["weather_evidence"]
    if knowledge_ev is None and record.get("knowledge_evidence") is not None:
        citations = record["knowledge_evidence"]
        if citations:
            knowledge_ev = {"status": "ok", "citation": citations,
                            "result": {"segments": [], "no_match": False}}
    if model_ev is None:
        me = record.get("model_evidence") or {}
        pred = me.get("source_prediction")
        if pred:
            model_ev = {"status": "ok", "result": pred,
                        "model_version": me.get("model_version", record.get("model_version", "?"))}
        else:
            pred = (record.get("step3_model_prediction") or record.get("prediction")
                    or ((record.get("internal_baseline") or {}).get("prediction")))
            if pred:
                model_ev = {"status": "ok", "result": pred,
                            "model_version": record.get("model_version", "?")}

    # 历史逐点序列（多结构兼容）
    samples = None
    if record.get("history_series"):
        samples = record["history_series"]
    elif record.get("history_window"):
        samples = record["history_window"]
    elif record.get("history_samples"):
        samples = record["history_samples"]  # 创新点1 实验记录结构
    elif (record.get("step2_recent_history_3h") or {}).get("data", {}).get("samples"):
        samples = record["step2_recent_history_3h"]["data"]["samples"]
    elif (record.get("internal_baseline") or {}).get("history", {}).get("data", {}).get("samples"):
        samples = record["internal_baseline"]["history"]["data"]["samples"]
    elif history_ev and (history_ev.get("result") or {}).get("temperature_first") is not None:
        r = history_ev["result"]
        samples = [{"temperature": r.get("temperature_first")},
                   {"temperature": r.get("temperature_last")}]  # 仅首末（点数不足 7 → 降分）
    return {"history": history_ev, "weather": weather_ev,
            "knowledge": knowledge_ev, "model": model_ev, "samples": samples}


# ---------------- 单项打分 ----------------

def score_history(samples):
    if samples is None:
        return None  # 无此证据类型
    if not samples:
        return 0.0
    s = 1.0
    if len(samples) < 7:
        s -= 0.1 * (7 - len(samples))  # 有效历史点不足 7 个 → 降分
    for p in samples:
        for f, (lo, hi) in BOUNDS.items():
            v = p.get(f)
            if v is not None and not (lo <= v <= hi):
                s -= 0.2  # 数值越界
    for i in range(1, len(samples)):
        dt = samples[i].get("temperature", 0) - samples[i - 1].get("temperature", 0)
        dh = samples[i].get("humidity", 0) - samples[i - 1].get("humidity", 0)
        if abs(dt) > 5 or abs(dh) > 20:
            s -= 0.1  # 离群跳变
    return round(max(0.0, min(1.0, s)), 2)


def score_weather(weather_ev):
    if weather_ev is None:
        return None  # 无天气证据
    status = weather_ev.get("status")
    if status in ("error", "unavailable", None):
        return 0.0  # 调用失败 / 超时
    data = weather_ev.get("data") or weather_ev
    # 兼容两种结构：B05 工具模板（forecast.hourly 嵌套）与冻结快照（顶层 hourly）
    hourly = ((data.get("forecast") or {}).get("hourly")
              or data.get("hourly") or [])
    forecast_time = weather_ev.get("forecast_time") or data.get("forecast_time")
    if not hourly or not forecast_time:
        return 0.0  # 字段缺失
    return 1.0


def score_knowledge(knowledge_ev):
    if knowledge_ev is None:
        return None
    result = knowledge_ev.get("result") or {}
    if result.get("no_match"):
        return 0.0  # 检索无匹配 → 匹配度最低
    segments = result.get("segments") or []
    citation = knowledge_ev.get("citation") or []
    if not citation:
        return 0.2  # citation 缺失
    if not segments:
        return 0.4  # citation 存在但无片段详情（匹配度未知，取中间分）
    scores = [seg.get("score", 0) for seg in segments if seg.get("score") is not None]
    if not scores:
        return 0.4
    match = min(sum(scores) / len(scores) / 8.0, 1.0)  # B04 检索得分归一化
    return round(min(1.0, 0.5 + 0.5 * match), 2)  # 匹配度低 → 降分


def score_model(model_ev):
    if model_ev is None:
        return None
    result = model_ev.get("result") or {}
    proba = result.get("probability") or {}
    values = [v for v in proba.values() if isinstance(v, (int, float))]
    if not values:
        return 0.0
    top = max(values)
    if top >= 0.7:
        return 1.0
    if top >= 0.5:
        return 0.7
    return 0.4


# ---------------- 综合打分 ----------------

def confidence_note(conf):
    if conf >= 0.8:
        return "证据充足，参考价值高"
    if conf >= 0.4:
        return "证据存在瑕疵，结论仅供参考"
    return "证据质量差，建议复核数据源"


def score_record(record):
    """对一条记录打分。文件损坏/字段缺失 → 快照完整性降分。"""
    ev = extract_evidence(record)
    scores = {
        "history": score_history(ev["samples"]),
        "weather": score_weather(ev["weather"]),
        "knowledge": score_knowledge(ev["knowledge"]),
        "model": score_model(ev["model"]),
    }
    # 快照完整性：核心字段缺失 → 综合与单项同步降分（每缺一项扣 0.1，最多 0.3）
    required = ("run_id", "created_at") if record.get("run_id") else ("run_id",)
    integrity_penalty = sum(0.1 for f in ("run_id", "created_at") if not record.get(f))
    integrity_penalty = min(integrity_penalty, 0.3)

    # 综合：仅对非 null 单项按任务权重归一化
    active = {k: v for k, v in scores.items()
              if k in WEIGHTS and v is not None}
    if not active:
        total = 0.0
    else:
        w_sum = sum(WEIGHTS[k] for k in active)
        total = sum(WEIGHTS[k] * active[k] for k in active) / w_sum
    total = round(max(0.0, min(1.0, total - integrity_penalty)), 2)
    return {
        "evidence_score": scores,
        "confidence_total": total,
        "confidence_note": confidence_note(total),
        "weights": WEIGHTS,
        "integrity_penalty": integrity_penalty,
    }


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="证据可信度打分（只读批量分析）")
    parser.add_argument("--file", help="单个 json 存档")
    parser.add_argument("--dir", help="批量处理目录下的 json 存档")
    args = parser.parse_args()

    paths = []
    if args.file:
        paths = [Path(args.file)]
    elif args.dir:
        paths = sorted(Path(args.dir).glob("*.json"))
    if not paths:
        parser.print_help()
        return 1

    for path in paths:
        try:
            record = load_json(path)
        except Exception as e:
            print("%s：文件损坏，无法解析（%s）→ confidence_total=0.0，"
                  "confidence_note=证据质量差，建议复核数据源" % (path.name, e))
            continue
        result = score_record(record)
        print("%s | 综合=%.2f（%s）| 时序=%s 天气=%s 知识=%s 模型=%s" % (
            path.name, result["confidence_total"], result["confidence_note"],
            result["evidence_score"]["history"], result["evidence_score"]["weather"],
            result["evidence_score"]["knowledge"], result["evidence_score"]["model"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
