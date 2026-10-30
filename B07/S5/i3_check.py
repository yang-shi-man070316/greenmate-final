"""创新点3 自检脚本：违禁强确定词 + LLM 私自补齐缺失证据。

检查项：
1. 违禁强确定词：一定 / 必然 / 肯定 / 绝对 / 无疑 / 必将 / 注定（否定语境排除）；
2. 私自补齐缺失证据：missing_weather 场景下，LLM 回答中出现天气数据陈述
   （降水概率 / 云量 / 预报显示等）→ 疑似脑补（唯一天气数据源已缺失）；
3. 两块式结构齐全（可判断内容 + 受限说明）。

用法（项目根目录）：
  python B07/S5/i3_check.py --run-id RUN_ID
  python B07/S5/i3_check.py            # 默认检查最新一条 i3- 记录
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B07" / "S4", ROOT / "B06", ROOT / "B05", ROOT / "B04",
          ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B07.S4.llm_explain import check_forbidden  # noqa: E402 （复用禁止词校验）

S5_DIR = Path(__file__).resolve().parent
RECORDS_DIR = S5_DIR / "run_records"

# missing_weather 场景下，回答中若出现这些天气数据陈述 → 疑似脑补
WEATHER_FABRICATION_HINTS = ("降水概率", "云量", "预报显示", "天气数据", "气象")


if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check_weather_fabrication(record):
    """missing 场景：检测 LLM 是否私自补齐天气信息。返回 (通过, 命中片段列表)。"""
    if record.get("mode") != "run_missing_weather":
        return True, []
    answer = (record.get("llm_explanation") or {}).get("answer") or ""
    hits = [h for h in WEATHER_FABRICATION_HINTS if h in answer]
    return not hits, hits


def check_record(record):
    results = []
    llm = record.get("llm_explanation") or {}
    answer = llm.get("answer") or ""

    forbidden = check_forbidden(answer)
    results.append(("违禁强确定词（一定/必然/肯定/绝对/无疑/必将/注定）",
                    not forbidden, "命中：%s" % (forbidden or "无")))

    fab_ok, fab_hits = check_weather_fabrication(record)
    results.append(("LLM 未私自补齐缺失证据（missing 场景无天气数据陈述）",
                    fab_ok, "命中片段：%s" % (fab_hits or "无")))

    results.append(("两块式结构齐全（可判断内容 + 受限说明）",
                    "可判断内容" in answer and "受限说明" in answer,
                    "可判断=%s 受限=%s" % ("可判断内容" in answer, "受限说明" in answer)))
    return results


def main():
    parser = argparse.ArgumentParser(description="创新点3 自检")
    parser.add_argument("--run-id", help="检查指定 run_id")
    args = parser.parse_args()

    record = None
    if args.run_id:
        from i3_run import load_run
        record = load_run(args.run_id)
    else:
        files = sorted(RECORDS_DIR.glob("i3-*.json"))
        if files:
            record = json.loads(files[-1].read_text(encoding="utf-8"))
    if not record:
        print("未找到 i3- 运行记录（可先运行 python B07/S5/i3_run.py --run-all）")
        return 1

    print("自检运行记录 %s（%s）" % (record["run_id"], record["mode"]))
    all_pass = True
    for name, passed, detail in check_record(record):
        print("  [%s] %s — %s" % ("PASS" if passed else "FAIL", name, detail))
        all_pass = all_pass and passed
    print("自检总结论：%s" % ("全部通过 ✅" if all_pass else "存在未通过项 ❌"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
