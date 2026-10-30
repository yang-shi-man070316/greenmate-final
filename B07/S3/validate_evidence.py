"""创新点2 证据校验脚本（B07/S3 交付物）。

校验规则：
1. 基础字段齐全：source_type / source / time / status / result（error 按需）；
2. status 仅 ok / unavailable / error；
3. 按证据类型校验扩展字段：ml_prediction 必须有 model_version、
   local_knowledge 必须有 citation、external_weather 建议有 provider；
4. status=ok 时 result 必须非空；status!=ok 时必须有 error。

用法（项目根目录）：
  python B07/S3/validate_evidence.py                 # 校验 S4 最新一轮运行记录中的证据
  python B07/S3/validate_evidence.py --run-id xxx    # 校验指定 run_id 记录中的证据
  python B07/S3/validate_evidence.py --self-test     # 内置样例自检
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B07" / "S4", ROOT / "B06", ROOT / "B05", ROOT / "B04",
          ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from i2_evidence import ALLOWED_STATUS, SOURCE_TYPES, make_evidence  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

EXTRA_FIELDS = {
    "ml_prediction": ["model_version"],
    "local_knowledge": ["citation"],
    "external_weather": ["provider", "forecast_time"],
    "internal_history": [],
}


def validate(evidence):
    """返回问题列表（空列表 = 通过）。"""
    problems = []
    if evidence.get("source_type") not in SOURCE_TYPES:
        problems.append("非法 source_type：%s" % evidence.get("source_type"))
    for field in ("source", "time", "status", "result"):
        if evidence.get(field) is None:
            problems.append("缺少基础字段：%s" % field)
    if evidence.get("status") not in ALLOWED_STATUS:
        problems.append("非法 status：%s（仅允许 %s）" % (evidence.get("status"), ALLOWED_STATUS))
    elif evidence.get("status") == "ok" and evidence.get("result") in (None, "", {}):
        problems.append("status=ok 但 result 为空")
    elif evidence.get("status") != "ok" and not evidence.get("error"):
        problems.append("status=%s 但缺少 error" % evidence.get("status"))
    st = evidence.get("source_type")
    for field in EXTRA_FIELDS.get(st, []):
        if field == "citation":
            if evidence.get(field) is None:
                problems.append("%s 证据缺少扩展字段：citation（知识引用）" % st)
        elif st == "ml_prediction" and not evidence.get(field):
            problems.append("ml_prediction 证据缺少扩展字段：model_version")
        elif st == "external_weather" and field == "provider" and not evidence.get(field):
            problems.append("external_weather 证据缺少扩展字段：provider")
    return problems


def validate_record(record):
    """校验一条运行记录中的全部证据，返回逐条结果。"""
    results = []
    for ev in record.get("adopted_evidence", []) + record.get("evidence", []):
        problems = validate(ev)
        results.append({
            "evidence_id": ev.get("evidence_id", "?"),
            "source_type": ev.get("source_type"),
            "passed": not problems,
            "problems": problems,
        })
    return results


def self_test():
    """内置样例自检：合法证据通过、违规证据被查出。"""
    cases = [
        ("合法历史证据", make_evidence("internal_history", "greenmate_b02_db", "ok",
                                        result={"trend": "持续升温"}), []),
        ("合法预测证据（含 model_version）", make_evidence(
            "ml_prediction", "greenmate_b06_rf", "ok",
            result={"predicted_attention": "WATCH"}, model_version="b06-rf-v1"), []),
        ("合法知识证据（含 citation）", make_evidence(
            "local_knowledge", "greenmate_b04_kb", "ok",
            result={"segments": [{"id": "K09"}]}, citation=[{"id": "K09"}]), []),
        ("合法天气证据（含 provider）", make_evidence(
            "external_weather", "open_meteo", "ok",
            result={"forecast": {"hourly": []}}, provider="open_meteo",
            forecast_time=["2026-10-29T20:00"]), []),
        ("非法 status（绕过封装的原始字典，校验器应检出）",
         {"source_type": "internal_history", "source": "x", "time": "t",
          "status": "bogus", "result": {}}, ["非法 status"]),
        ("预测证据缺 model_version", make_evidence(
            "ml_prediction", "greenmate_b06_rf", "ok",
            result={"predicted_attention": "NORMAL"}), ["model_version"]),
        ("error 状态缺 error 说明", make_evidence(
            "external_weather", "open_meteo", "error",
            result=None, provider="open_meteo"), ["error"]),
    ]
    all_pass = True
    for name, ev, expect_hints in cases:
        problems = validate(ev)
        hint_ok = all(any(h in p for p in problems) for h in expect_hints)
        passed = bool(problems) == bool(expect_hints) and hint_ok
        all_pass = all_pass and passed
        print("[%s] %s → 问题：%s" % ("PASS" if passed else "FAIL", name, problems or "无"))
    return 0 if all_pass else 1


def main():
    parser = argparse.ArgumentParser(description="创新点2 证据校验")
    parser.add_argument("--run-id", help="校验指定 run_id 记录中的证据")
    parser.add_argument("--self-test", action="store_true", help="内置样例自检")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    run_id = args.run_id
    record = None
    if run_id:
        from B07.S4.run import load_run
        record = load_run(run_id)
    else:
        # 默认：S4 最新一轮 with_evidence 记录
        import glob
        files = sorted(glob.glob(str(ROOT / "B07" / "S4" / "run_records" / "s4-*.json")))
        for path in reversed(files):
            r = json.loads(Path(path).read_text(encoding="utf-8"))
            if r.get("experiment") == "S4_with_evidence":
                record = r
                break
    if not record:
        print("未找到可校验的运行记录（可先运行 python B07/S4/run.py --with_evidence）")
        return 1

    print("校验运行记录 %s（experiment=%s）" % (record.get("run_id"), record.get("experiment")))
    results = validate_record(record)
    all_pass = True
    for r in results:
        print("  [%s] %s（%s）%s" % ("PASS" if r["passed"] else "FAIL", r["evidence_id"],
                                     r["source_type"], r["problems"] or ""))
        all_pass = all_pass and r["passed"]
    print("校验总结论：%s" % ("全部通过 ✅" if all_pass else "存在未通过项 ❌"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
