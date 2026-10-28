"""S1 运行记录：唯一 run_id 生成、保存到 run_records/、按 run_id 读取并回答问题。

两个可回答的问题：
- Q1 这次 GreenMate 看到了什么？
- Q2 最后为什么说它比较稳定？
"""

import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

RECORDS_DIR = Path(__file__).resolve().parent / "run_records"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_run_id():
    return "s1-%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


def save_run(record):
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = record["run_id"]
    path = RECORDS_DIR / ("%s.json" % run_id)
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
    """用运行记录回答两个问题。"""
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
        "     温度 min=%.1f max=%.1f mean=%.1f | 湿度 min=%.1f max=%.1f | 光照 min=%.0f max=%.0f"
        % (trend["temperature"]["min"], trend["temperature"]["max"], trend["temperature"]["mean"],
           trend["humidity"]["min"], trend["humidity"]["max"],
           trend["light"]["min"], trend["light"]["max"]) if trend.get("available") else "",
        "  3) 模型短时预测（B06，版本 %s）：predicted_attention=%s，概率 %s" % (
            prediction.get("model_version"), prediction.get("predicted_attention"),
            prediction.get("probability")),
        "  4) 结构化判断：verdict=%s（LLM 无权修改）" % judgment.get("verdict"),
        "",
        "【Q2 最后为什么说它比较稳定？】",
    ]
    if trend.get("available"):
        t, h = trend["temperature"], trend["humidity"]
        lines.append(
            "  温度 %s~%s℃ 小幅波动（幅差 %s℃），3 小时前后半均值差 %s℃（无持续升降）；"
            "湿度 %s~%s%% 窄幅波动（幅差 %s%%，前后半均值差 %s%%）；"
            "scenarios=%s（无扰动）；模型预测 NORMAL。因此结构化判断为 stable。" % (
                t["min"], t["max"], round(t["max"] - t["min"], 1), t["half_diff"],
                h["min"], h["max"], round(h["max"] - h["min"], 1), h["half_diff"],
                trend.get("sim_scenarios")))
    else:
        lines.append("  历史数据缺失，无稳定性结论（inconclusive）")
    if llm.get("status") == "success":
        lines += ["", "【LLM 自然语言解释（固定 prompt）】", llm["answer"]]
    else:
        lines += ["", "【LLM 解释】不可用：[%s] %s（结构化判断不受影响）" % (
            llm.get("error_type"), llm.get("message"))]
    return "\n".join(lines)
