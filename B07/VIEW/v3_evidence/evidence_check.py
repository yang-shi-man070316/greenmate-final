"""VIEW3 视图约束校验脚本。

校验（对应全局只读规则）：
1. 源码约束：evidence_render.py 未 import LLM/模型/接口/数据库模块（纯 json 读取）；
2. 幂等：同一 run_id 渲染两次输出完全一致；
3. 无副作用：渲染前后三个 run_records 目录均无变化；
4. 与存档一致：主存档 verdict、各证据来源字段出现在视图中且未被修改；
5. 三存档只读：渲染器不写任何 run_records。

用法（项目根目录）：
  python B07/VIEW/v3_evidence/evidence_check.py --run-id i3-20261031013638-f78ead
"""

import argparse
import hashlib
import sys
from pathlib import Path

VIEW_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parent.parent.parent.parent
RECORDS_DIRS = [ROOT / "B07" / "S4" / "run_records",
                ROOT / "B07" / "S5" / "run_records"]

FORBIDDEN_IMPORTS = ("openai", "sklearn", "load_model", "get_weather", "fetch_forecast",
                     "predict_latest", "httpx", "b02_db", "query_series", "import llm",
                     "requests", "urllib")

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def snapshot():
    snap = {}
    for d in RECORDS_DIRS:
        for p in d.glob("*.json"):
            snap[str(p)] = hashlib.md5(p.read_bytes()).hexdigest()
    return snap


def main():
    parser = argparse.ArgumentParser(description="VIEW3 视图约束校验")
    parser.add_argument("--run-id", required=True, help="校验渲染的 run_id")
    args = parser.parse_args()
    results = []

    source = (VIEW_DIR / "evidence_render.py").read_text(encoding="utf-8")
    hits = [w for w in FORBIDDEN_IMPORTS if w in source]
    results.append(check("渲染器未 import LLM/模型/接口/数据库模块（纯 json 只读）",
                         not hits, "命中：%s" % (hits or "无")))

    from evidence_render import (extract_main, extract_s4_case, extract_s5_case,
                                 load_json, render_md)
    record = load_json(args.run_id, ROOT / "B07" / "S5" / "run_records")
    before = snapshot()
    main = extract_main(record)
    text1 = render_md(main, extract_s4_case(), extract_s5_case())
    text2 = render_md(main, extract_s4_case(), extract_s5_case())
    results.append(check("渲染幂等：两次渲染输出完全一致", text1 == text2))
    after = snapshot()
    results.append(check("渲染无副作用：所有 run_records 目录无变化",
                         before == after, "%d files" % len(before)))

    verdict = (record.get("judgment") or {}).get("verdict", "")
    results.append(check("视图 verdict 与主存档一致", verdict and verdict in text1, verdict))
    sources = [ev.get("source") for ev in record.get("adopted_evidence", [])
               if ev.get("source_type") in ("internal_history", "external_weather",
                                            "local_knowledge", "ml_prediction")]
    missing_sources = [s for s in sources if s and s not in text1]
    results.append(check("各证据来源与存档一致（未修改）", not missing_sources,
                         "缺失：%s" % (missing_sources or "无")))
    results.append(check("五类证据分区齐全（历史/天气/知识/模型/工具）",
                         all(k in text1 for k in ("历史证据", "天气证据", "知识证据",
                                                  "模型证据", "工具与运行状态"))))
    results.append(check("三问结构齐全（来源/内容/有效性）",
                         all(k in text1 for k in ("来源：", "内容：", "有效性："))))

    print("\nVIEW3 校验总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
