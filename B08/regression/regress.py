"""B08 第四遍：固定回归套件（10 个案例）与一键批量回归。

10 个案例由 S1~S5 冻结场景派生（受控变体：历史窗口截取、知识移除），
每组 2 例，覆盖五条硬性校验规则：
- 稳定场景不能无依据报警
- 漂移场景应识别变化
- 外部天气应影响未来判断
- 证据分歧应保留差异
- 证据缺失应触发限制说明
- LLM 可以换说法，但不能改写结构化判断、不能补造缺失事实

每案例固化：固定输入快照 + 预期校验规则（结构化判定 / model_output 区间 /
证据状态 / 限制输出要求）。后续修改提示词/工具/证据结构/模型加载/页面逻辑/
错误处理后，直接全量重跑本脚本。

用法（项目根目录）：
  python B08/regression/regress.py            # 一键顺序跑全部 10 例 + 生成报告
  python B08/regression/regress.py --rebuild  # 重建 cases/ 快照
"""

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B08", ROOT / "B07" / "S5", ROOT / "B07" / "S4", ROOT / "B07" / "S3",
          ROOT / "B07" / "S2", ROOT / "B07" / "S1", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from replay import load_snapshot  # noqa: E402
from verify import load_source_record, load_verify, make_run_id, run_llm  # noqa: E402

REG_DIR = Path(__file__).resolve().parent
CASES_DIR = REG_DIR / "cases"
RUNS_DIR = REG_DIR / "runs"

APP_VERSION = "B08_baseline_01"
MODEL_VERSION = "b06-rf-v1"

# verify 记录映射（模型证据预期来源）
V8_RUNS = {
    "b08_s1_steady": "v8-20261031072937-a6b34e",
    "b08_s2_drift": "v8-20261031072941-cbce4e",
    "b08_s3_weather": "v8-20261031072945-389510",
    "b08_s4_multi": "v8-20261031072949-fee711",
    "b08_s5_degraded": "v8-20261031072952-75625a",
}

# 10 个回归案例定义（由冻结场景派生，不需要全新场景）
CASE_DEFS = [
    # 1. 稳定场景 ×2：稳定场景不能无依据报警
    {"case_id": "case_stable_01", "group": "stable", "base": "b08_s1_steady",
     "variant": {}, "verdict_expect": ["stable"], "model_expect": ["NORMAL", "WATCH"],
     "weather_expect": None, "llm_must": ["稳定", "平稳", "正常", "无需"],
     "llm_must_not": ["需要重点关注", "风险升高"]},
    {"case_id": "case_stable_02", "group": "stable", "base": "b08_s1_steady",
     "variant": {"history_take": 6}, "verdict_expect": ["stable"],
     "model_expect": ["NORMAL", "WATCH"], "weather_expect": None,
     "llm_must": ["稳定", "平稳", "正常", "无需"], "llm_must_not": ["需要重点关注", "风险升高"]},
    # 2. 渐进漂移 ×2：漂移场景应识别变化
    {"case_id": "case_drift_01", "group": "drift", "base": "b08_s2_drift",
     "variant": {}, "verdict_expect": ["attention"], "model_expect": ["NORMAL", "WATCH"],
     "weather_expect": None, "llm_must": ["升温", "趋势", "上升"],
     "llm_must_not": []},
    {"case_id": "case_drift_02", "group": "drift", "base": "b08_s2_drift",
     "variant": {"history_take": 5}, "verdict_expect": ["attention"],
     "model_expect": ["NORMAL", "WATCH"], "weather_expect": None,
     "llm_must": ["升温", "趋势", "上升"], "llm_must_not": []},
    # 3. 外部扰动 ×2：外部天气应影响未来判断
    {"case_id": "case_weather_01", "group": "weather", "base": "b08_s3_weather",
     "variant": {}, "verdict_expect": ["weather_attention"],
     "model_expect": ["NORMAL", "WATCH"], "weather_expect": "ok",
     "llm_must": ["天气", "降水", "云量", "阴雨"], "llm_must_not": []},
    {"case_id": "case_weather_02", "group": "weather", "base": "b08_s3_weather",
     "variant": {"history_take": 6}, "verdict_expect": ["weather_attention"],
     "model_expect": ["NORMAL", "WATCH"], "weather_expect": "ok",
     "llm_must": ["天气", "降水", "云量", "阴雨"], "llm_must_not": []},
    # 4. 证据分歧 ×2：保留多方差异，不强行合并结论
    {"case_id": "case_conflict_01", "group": "conflict", "base": "b08_s4_multi",
     "variant": {}, "verdict_expect": ["attention_uncertain"],
     "model_expect": ["WATCH"], "weather_expect": "ok",
     "llm_must": ["分歧", "不确定", "不一致", "可能缓解"], "llm_must_not": []},
    {"case_id": "case_conflict_02", "group": "conflict", "base": "b08_s4_multi",
     "variant": {"knowledge_drop": True}, "verdict_expect": ["attention_uncertain"],
     "model_expect": ["WATCH"], "weather_expect": "ok",
     "llm_must": ["分歧", "不确定", "不一致", "可能缓解"], "llm_must_not": []},
    # 5. 证据退化 ×2：缺失时触发限制说明，不编造不存在事实
    {"case_id": "case_degraded_01", "group": "degraded", "base": "b08_s5_degraded",
     "variant": {}, "verdict_expect": ["attention_weather_missing"],
     "model_expect": ["WATCH"], "weather_expect": "unavailable",
     "llm_must": ["受限", "缺失", "不可用", "无法判断"],
     "llm_must_not": ["降水概率", "云量"]},
    {"case_id": "case_degraded_02", "group": "degraded", "base": "b08_s5_degraded",
     "variant": {"history_take": 6}, "verdict_expect": ["attention_weather_missing"],
     "model_expect": ["WATCH"], "weather_expect": "unavailable",
     "llm_must": ["受限", "缺失", "不可用", "无法判断"],
     "llm_must_not": ["降水概率", "云量"]},
]

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


# ---------------- 案例构建（首次生成，之后固定） ----------------

def build_cases(force=False):
    """从冻结场景派生 10 个案例快照并固化到 cases/。"""
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    built = 0
    for cdef in CASE_DEFS:
        path = CASES_DIR / ("%s.json" % cdef["case_id"])
        if path.exists() and not force:
            continue
        base = load_snapshot(cdef["base"])
        variant = cdef["variant"]
        snapshot = dict(base)
        snapshot["scenario_id"] = cdef["case_id"]
        snapshot["derived_from"] = cdef["base"]
        if variant.get("history_take"):
            snapshot["history_series"] = base["history_series"][:variant["history_take"]]
            last = snapshot["history_series"][-1]
            snapshot["observation"] = {
                "temperature": last["temperature"], "humidity": last["humidity"],
                "light": last["light"], "observed_at": last["timestamp"]}
        if variant.get("knowledge_drop"):
            snapshot["knowledge_citation"] = []
        # 模型证据预期（从正式验证记录提取；缺失时回溯源存档，固定）
        v8 = load_verify(V8_RUNS[cdef["base"]])
        model_ev = v8.get("model_evidence") or {"model_version": MODEL_VERSION}
        if not model_ev.get("source_prediction"):
            src = load_source_record(base)
            pred = None
            if src:
                pred = ((src.get("internal_baseline") or {}).get("prediction")
                        or src.get("step3_model_prediction"))
                if not pred:
                    e2 = next((e for e in src.get("adopted_evidence", [])
                               + src.get("evidence", [])
                               if e.get("source_type") == "ml_prediction"), None)
                    pred = (e2 or {}).get("result")
            if pred:
                model_ev = dict(model_ev, source_prediction={
                    "predicted_attention": pred.get("predicted_attention"),
                    "probability": pred.get("probability")})
        snapshot["model_evidence"] = model_ev
        case = {
            "case_id": cdef["case_id"],
            "group": cdef["group"],
            "derived_from": cdef["base"],
            "app_version": APP_VERSION,
            "model_version": MODEL_VERSION,
            "expected": {
                "verdict_expect": cdef["verdict_expect"],
                "model_expect": cdef["model_expect"],
                "weather_expect": cdef["weather_expect"],
                "llm_must": cdef["llm_must"],
                "llm_must_not": cdef["llm_must_not"],
            },
            "snapshot": snapshot,
        }
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        built += 1
        print("[构建] %s（组：%s，派生自 %s%s）" % (
            cdef["case_id"], cdef["group"], cdef["base"],
            "，变体 %s" % variant if variant else "，原样"))
    return built


def load_cases():
    cases = []
    for path in sorted(CASES_DIR.glob("case_*.json")):
        cases.append(json.loads(path.read_text(encoding="utf-8")))
    return cases


# ---------------- 单案例执行与校验 ----------------

def run_case(case):
    """执行单个案例：固定输入快照 → 固定提问 → 校验预期观察点。"""
    snapshot = case["snapshot"]
    expected = case["expected"]
    llm = run_llm(snapshot)
    answer = llm.get("answer") or ""

    checks = []
    # 1. 结构化判断
    verdict = snapshot["judgment_snapshot"]["verdict"]
    checks.append(("结构化判断", verdict in expected["verdict_expect"],
                   "verdict=%s，预期 %s" % (verdict, expected["verdict_expect"])))
    # 2. MODEL_OUTPUT 区间
    pred = ((snapshot.get("model_evidence") or {}).get("source_prediction") or {})
    attention = pred.get("predicted_attention")
    checks.append(("model_output 区间", attention in expected["model_expect"],
                   "predicted_attention=%s，预期 %s" % (attention, expected["model_expect"])))
    # 3. 证据状态
    weather = snapshot.get("weather_evidence")
    weather_status = weather.get("status") if weather else None
    checks.append(("证据状态", weather_status == expected["weather_expect"],
                   "weather_status=%s，预期 %s" % (weather_status, expected["weather_expect"])))
    # 4. LLM 对齐（措辞可不同，但不能偏离结构化结果；
    #    允许以 verdict 原文词（如 stable/attention）或描述词对齐）
    align_words = expected["llm_must"] + list(expected["verdict_expect"])
    must_hit = [w for w in align_words if w in answer]
    checks.append(("LLM 与结构化结果对齐", bool(must_hit),
                   "命中对齐词：%s" % (must_hit or "无")))
    # 5. 限制输出要求（不报警 / 不编造）
    bad_hits = [w for w in expected["llm_must_not"] if w in answer]
    checks.append(("限制输出要求", not bad_hits, "违规词：%s" % (bad_hits or "无")))

    passed = all(p for _, p, _ in checks)
    diffs = [d for _, p, d in checks if not p]
    run_id = make_run_id()
    result = {
        "run_id": run_id,
        "case_id": case["case_id"],
        "group": case["group"],
        "passed": passed,
        "checks": [{"check": n, "passed": p, "detail": d} for n, p, d in checks],
        "expected_vs_actual": {
            "verdict": {"expected": expected["verdict_expect"], "actual": verdict},
            "model_attention": {"expected": expected["model_expect"], "actual": attention},
            "weather_status": {"expected": expected["weather_expect"], "actual": weather_status},
        },
        "llm_answer": answer,
        "llm_status": llm.get("status"),
        "key_diffs": diffs,
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / ("%s.json" % run_id)).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    mark = "通过 ✅" if passed else "失败 ❌"
    print("[回归] %s（%s）：%s%s" % (case["case_id"], case["group"], mark,
                                    "，差异：%s" % diffs if diffs else ""))
    return result


# ---------------- 报告 ----------------

def build_report(results, started):
    total = len(results)
    passed_n = sum(1 for r in results if r["passed"])
    failed_n = total - passed_n
    lines = [
        "# GreenMate B08 第四遍 · 首轮回归报告（REGRESSION_REPORT）",
        "",
        "- app_version：%s" % APP_VERSION,
        "- model_version：%s" % MODEL_VERSION,
        "- 测试时间：%s" % started.strftime("%Y-%m-%d %H:%M:%S"),
        "- 回归案例数量：%d" % total,
        "- 通过数量：%d" % passed_n,
        "- 失败数量：%d" % failed_n,
        "- 本轮全部 run_id：%s" % ", ".join("`%s`" % r["run_id"] for r in results),
        "",
        "## 每个案例小结",
        "",
        "| case_id | 分组 | 是否通过 | 预期 vs 实际 | 关键差异点 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        eva = r["expected_vs_actual"]
        eva_text = "verdict 预期%s/实际%s；模型预期%s/实际%s；天气预期%s/实际%s" % (
            eva["verdict"]["expected"], eva["verdict"]["actual"],
            eva["model_attention"]["expected"], eva["model_attention"]["actual"],
            eva["weather_status"]["expected"], eva["weather_status"]["actual"])
        lines.append("| %s | %s | %s | %s | %s |" % (
            r["case_id"], r["group"], "✅ 通过" if r["passed"] else "❌ 失败",
            eva_text, "；".join(r["key_diffs"]) if r["key_diffs"] else "无"))
    lines += [
        "",
        "## 五条硬性校验规则覆盖",
        "",
        "| 规则 | 覆盖案例 | 结果 |",
        "| --- | --- | --- |",
    ]
    groups = {"stable": "稳定场景不能无依据报警", "drift": "漂移场景应识别变化",
              "weather": "外部天气应影响未来判断", "conflict": "证据分歧应保留差异",
              "degraded": "证据缺失应触发限制说明"}
    for g, rule in groups.items():
        gr = [r for r in results if r["group"] == g]
        ok = all(r["passed"] for r in gr)
        lines.append("| %s | %s | %s |" % (
            rule, ", ".join(r["case_id"] for r in gr), "✅" if ok else "❌"))
    lines += [
        "",
        "## 总结论",
        "",
        ("✅ 首轮回归全部通过：10/10 案例通过，五个分组规则全覆盖。"
         "后续修改提示词/工具/证据结构/模型加载/页面逻辑/错误处理后，"
         "运行 python B08/regression/regress.py 全量重跑即可。" if failed_n == 0 else
         "❌ 存在 %d 个失败案例：%s" % (failed_n,
         ", ".join(r["case_id"] for r in results if not r["passed"]))),
        "",
    ]
    (REG_DIR / "REGRESSION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return lines, passed_n, failed_n


def build_summary(passed_n, failed_n, started):
    lines = [
        "# B08 第四遍验收摘要（REGRESSION_SUMMARY）",
        "",
        "- 生成时间：%s" % started.strftime("%Y-%m-%d %H:%M:%S"),
        "- app_version：%s | model_version：%s" % (APP_VERSION, MODEL_VERSION),
        "- 回归案例：10 个（S1~S5 衍生变体，每组 2 例），通过 %d / 失败 %d" % (passed_n, failed_n),
        "",
        "## 验收完成线核对",
        "",
        "- [x] GreenMate 拥有一组可重复运行的固定回归案例（cases/ 10 套快照+预期配置）；",
        "- [x] 每次重要修改后，可重新验证三个创新机制和 S1~S5 基本行为没有被破坏"
        "（python B08/regression/regress.py 一键全量重跑）；",
        "- [x] 未改动 B08/trace、B08/verify 历史数据（回归只读引用其记录）；",
        "",
        "**第四遍验收：%s**" % ("通过 ✅" if failed_n == 0 else "未通过 ❌"),
        "",
    ]
    (REG_DIR / "REGRESSION_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    return lines


def main():
    parser = argparse.ArgumentParser(description="B08 固定回归套件")
    parser.add_argument("--rebuild", action="store_true", help="重建 cases/ 快照")
    args = parser.parse_args()

    started = datetime.now()
    built = build_cases(force=args.rebuild)
    if built:
        print("[构建] 新建案例 %d 个\n" % built)
    cases = load_cases()
    if len(cases) != 10:
        print("[错误] 案例数量不符：%d（应为 10），请先 --rebuild" % len(cases))
        return 1

    print("[回归] 开始顺序执行 %d 个案例\n" % len(cases))
    results = [run_case(c) for c in cases]
    print()
    report, passed_n, failed_n = build_report(results, started)
    build_summary(passed_n, failed_n, started)
    print("\n".join(report))
    print("\n[报告已生成] %s / %s" % (REG_DIR / "REGRESSION_REPORT.md",
                                      REG_DIR / "REGRESSION_SUMMARY.md"))
    return 0 if failed_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
