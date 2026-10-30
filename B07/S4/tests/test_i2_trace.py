"""创新点2 溯源实验测试（无需 LLM Key / 无需联网）。

- 证据封装：四类作用边界、五问 describe、字段与扩展字段；
- 证据校验：合法通过 / 违规检出（validate_evidence.self_test）；
- 结论抽取与证据方向绑定（支持/反向提示/限制）；
- 调用记录校验：真实调用、LLM 未假装调用（引用不存在的证据被检出）；
- 报告生成与 run_id/存档。

运行：python B07/S4/tests/test_i2_trace.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
S4 = Path(__file__).resolve().parent.parent  # B07/S4
for d in (ROOT / "B07" / "S3", ROOT / "B07" / "S4", ROOT / "B06", ROOT / "B05",
          ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT, S4):
    sys.path.insert(0, str(d))

from B07.S3.i2_evidence import ROLE_BOUNDARIES, describe, make_evidence, role_of  # noqa: E402
from B07.S3.validate_evidence import validate  # noqa: E402
from i2_trace import (annotate_conclusion, extract_conclusion, make_run_id,  # noqa: E402
                      verify_calls)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def main():
    results = []

    # 1. 四类作用边界（信息≠证据，不可互相替代）
    roles = {k: v["role"] for k, v in ROLE_BOUNDARIES.items()}
    results.append(check("四类证据作用边界定义齐全且互不相同",
                         roles == {"internal_history": "已发生事实",
                                   "external_weather": "外部潜在条件",
                                   "local_knowledge": "通用专业判断",
                                   "ml_prediction": "对未来窗口的推断"},
                         str(roles)))

    # 2. 证据封装与五问
    ev = make_evidence("ml_prediction", "greenmate_b06_rf", "ok",
                       result={"predicted_attention": "WATCH"}, model_version="b06-rf-v1")
    d = describe(ev)
    results.append(check("五问齐备（是什么/来源/时间/有效性/内容）",
                         all(k in d for k in ("what", "source", "time", "valid", "content"))
                         and d["valid"] and d["content"]["predicted_attention"] == "WATCH"))
    results.append(check("作用边界可查询（模型预测=对未来窗口的推断）",
                         role_of(ev)["role"] == "对未来窗口的推断"
                         and "不是已发生事实" in role_of(ev)["boundary"]))

    # 3. 证据校验（复用 validate_evidence）
    results.append(check("合法证据通过校验", validate(ev) == []))
    bad = make_evidence("ml_prediction", "x", "ok", result={"a": 1})
    problems = validate(bad)
    results.append(check("预测证据缺 model_version 被检出",
                         any("model_version" in p for p in problems), str(problems)))

    # 4. 结论抽取与方向绑定
    from B07.S4.judgment import build_judgment
    e1 = make_evidence("internal_history", "greenmate_b02_db", "ok", result={"trend": "升温"})
    e2 = make_evidence("ml_prediction", "greenmate_b06_rf", "ok",
                       result={"predicted_attention": "WATCH"}, model_version="b06-rf-v1")
    e3 = make_evidence("external_weather", "open_meteo", "ok",
                       result={"forecast": {"hourly": []}}, provider="open_meteo",
                       forecast_time=["2026-10-29T20:00"])
    e4 = make_evidence("local_knowledge", "greenmate_b04_kb", "ok",
                       result={"segments": [{"id": "K09"}]}, citation=[{"id": "K09"}])
    j = build_judgment([e1, e2, e3, e4])
    conclusion = extract_conclusion(j)
    ann = annotate_conclusion(j)
    results.append(check("核心结论由判定侧生成（非 LLM 自由文本）",
                         "提高关注" in conclusion, conclusion))
    results.append(check("结论绑定支持/反向提示/限制证据",
                         ann == {"support": ["E1", "E2"], "reverse": ["E3"],
                                 "limitation": ["E4"]}, str(ann)))

    # 5. 调用记录校验（工具真实调用 + LLM 未假装调用）
    log = [
        {"tool": "B02 历史查询", "tool_called": True, "tool_success": True,
         "converted_to_evidence": True, "adopted_in_judgment": True, "note": "ok"},
        {"tool": "B05 get_weather_forecast → B03", "tool_called": True, "tool_success": True,
         "converted_to_evidence": True, "adopted_in_judgment": True, "note": "ok"},
    ]
    record = {"evidence": [e1, e2], "pipeline_log": log,
              "llm_explanation": {"answer": "结论依据 [E1] [E2] 与 [E9]"}}
    checks = verify_calls(record)
    by_name = {c[0]: c for c in checks}
    results.append(check("采用证据均有真实调用记录",
                         by_name["证据 E1（internal_history）有真实工具调用记录"][1]))
    results.append(check("LLM 引用不存在的证据 [E9] 被检出（不允许假装调用）",
                         not by_name["LLM 引用证据均真实存在（无假装调用）"][1],
                         by_name["LLM 引用证据均真实存在（无假装调用）"][2]))

    # 6. run_id 与存档
    rid = make_run_id()
    results.append(check("run_id 为 i2- 前缀", bool(re.match(r"^i2-\d{14}-[0-9a-f]{6}$", rid)), rid))

    print("\n创新点2 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
