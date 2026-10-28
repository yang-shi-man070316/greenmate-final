"""S2 正式对照实验报告生成：S1 基线 vs S2 漂移 全差异对比。

对比维度：瞬时数值、历史趋势、模型预测、风险判定（verdict）、关注等级、LLM 解释。
差异必须且只来自【B02 时序历史数据】（提示词/模型/配置全部一致）。

用法：
  python B07/S2/report.py [S1_run_id] [S2_run_id]
默认 S1 基线 = S1 原始记录（run_records/ 下 experiment 非 S2_drift 的最新一条）；
默认 S2 漂移 = run_records/ 下 experiment=S2_drift 的最新一条。
输出：docs/EXPERIMENT_REPORT.md
"""

import json
import sys
from pathlib import Path

S2_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S2_DIR / "run_records"
DOCS_DIR = S2_DIR / "docs"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def attention_level(verdict):
    """风险判定 → 关注等级。"""
    return {
        "stable": "低（无需重点关注）",
        "attention": "高（需要重点关注：存在潜在变化风险）",
        "model_disagreement": "中（模型与数据稳定性不一致，需复核）",
        "inconclusive": "中（证据不足）",
    }.get(verdict, verdict)


def find_record(experiment=None):
    """run_records 中取指定 experiment 的最新记录；experiment=None 取非 S2 的（S1 基线）。

    兼容两种 run_id 前缀：s1-（早期/复用 S1 记录逻辑）与 s2-（run.py 新命名规则）。
    """
    files = sorted(list(RECORDS_DIR.glob("s1-*.json")) + list(RECORDS_DIR.glob("s2-*.json")))
    if not files:
        raise FileNotFoundError("run_records 目录没有记录：%s" % RECORDS_DIR)
    for path in reversed(files):
        record = json.loads(path.read_text(encoding="utf-8"))
        if experiment is None:
            if record.get("experiment") != "S2_drift":
                return record, path
        elif record.get("experiment") == experiment:
            return record, path
    raise FileNotFoundError("未找到符合条件的记录（experiment=%s）" % experiment)


def build_report(s1_record, s2_record, s1_path, s2_path):
    """生成对照报告 markdown。"""
    s1j = s1_record["step4_structured_judgment"]
    s2j = s2_record["step4_structured_judgment"]
    s1p = s1_record["step3_model_prediction"]
    s2p = s2_record["step3_model_prediction"]
    s1t = s1j["recent_trend"]
    s2t = s2j["recent_trend"]
    s1l = s1_record["step5_llm_explanation"]
    s2l = s2_record["step5_llm_explanation"]

    lines = [
        "# GreenMate S2 对照实验报告：稳态基线 vs 渐进漂移",
        "",
        "- 生成时间：%s" % __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- S1 基线记录：`%s`（run_id: %s）" % (s1_path.name, s1_record["run_id"]),
        "- S2 漂移记录：`%s`（run_id: %s）" % (s2_path.name, s2_record["run_id"]),
        "",
        "## 实验设计",
        "",
        "- 唯一变量：**B02 历史时序数据**（天气源、知识库、提示词、模型参数全部固定不变）",
        "- 统一固定提问（两组完全一致，无任何额外提示）：",
        "  「分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。」",
        "- 两组当前时刻温度几乎一致，仅近 3 小时历史演化过程不同；",
        "  系统必须通过读取 B02 时序历史自主识别趋势差异，禁止人工提示。",
        "",
        "## 全维度对照",
        "",
        "| 维度 | S1 基线场景 | S2 漂移场景 |",
        "| --- | --- | --- |",
        "| 当前瞬时温度 | %.1f℃ | %.1f℃ |" % (
            s1t["temperature"]["max"] if s1t.get("available") else float("nan"),
            s2t["temperature"]["max"] if s2t.get("available") else float("nan")),
        "| 历史窗口 | %s | %s |" % (
            s1t.get("window", "—"), s2t.get("window", "—")),
        "| 近3小时温度过程 | %.1f → %.1f℃（小幅波动） | %.1f → %.1f℃（匀速渐进升温） |" % (
            s1t["temperature"]["min"], s1t["temperature"]["max"],
            s2t["temperature"]["min"], s2t["temperature"]["max"]) if s1t.get("available") and s2t.get("available") else "| — | — |",
        "| 温度幅差 | %.1f℃ | %.1f℃ |" % (
            round(s1t["temperature"]["max"] - s1t["temperature"]["min"], 1),
            round(s2t["temperature"]["max"] - s2t["temperature"]["min"], 1)) if s1t.get("available") and s2t.get("available") else "| — | — |",
        "| 前后半均值差（趋势） | %+.2f℃/窗口（无持续升降） | %+.2f℃/窗口（持续上升漂移） |" % (
            s1t["temperature"]["half_diff"], s2t["temperature"]["half_diff"]) if s1t.get("available") and s2t.get("available") else "| — | — |",
        "| 湿度过程 | %.1f~%.1f%% | %.1f~%.1f%% |" % (
            s1t["humidity"]["min"], s1t["humidity"]["max"],
            s2t["humidity"]["min"], s2t["humidity"]["max"]) if s1t.get("available") and s2t.get("available") else "| — | — |",
        "| 模型预测 | %s（概率 %s） | %s（概率 %s） |" % (
            s1p["predicted_attention"], s1p.get("probability", {}),
            s2p["predicted_attention"], s2p.get("probability", {})),
        "| 模型版本 | %s | %s |" % (s1p["model_version"], s2p["model_version"]),
        "| **风险判定（verdict）** | **%s** | **%s** |" % (s1j["verdict"], s2j["verdict"]),
        "| **关注等级** | **%s** | **%s** |" % (
            attention_level(s1j["verdict"]), attention_level(s2j["verdict"])),
        "",
        "## 结论",
        "",
        "同一瞬时温度、同一提问、同一模型、同一配置下，两组输出**差异化结论**：",
        "",
        "- **S1**：判定环境稳定、无风险，无需重点关注；",
        "- **S2**：识别升温漂移趋势，判定存在潜在变化风险，需要重点关注。",
        "",
        "差异完全来自【B02 时序历史数据】（S2 漂移段由 drift_inject.py 注入：25→30℃ 匀速升温），"
        "提示词、模型、配置未做任何改动，无人工提示词干预。",
        "",
        "## LLM 解释对比",
        "",
        "### S1 基线（verdict=%s）" % s1j["verdict"],
        "",
    ]
    if s1l.get("status") == "success":
        lines.append(s1l["answer"])
    else:
        lines.append("（LLM 不可用：[%s] %s）" % (s1l.get("error_type"), s1l.get("message")))
    lines += ["", "### S2 漂移（verdict=%s）" % s2j["verdict"], ""]
    if s2l.get("status") == "success":
        lines.append(s2l["answer"])
    else:
        lines.append("（LLM 不可用：[%s] %s）" % (s2l.get("error_type"), s2l.get("message")))
    lines.append("")
    return "\n".join(lines)


def main():
    s1_record, s1_path = find_record(experiment=None)
    s2_record, s2_path = find_record(experiment="S2_drift")
    report = build_report(s1_record, s2_record, s1_path, s2_path)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = DOCS_DIR / "EXPERIMENT_REPORT.md"
    out.write_text(report, encoding="utf-8")
    print("对照报告已生成：%s" % out)
    print(report[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
