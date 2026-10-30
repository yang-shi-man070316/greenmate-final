"""VIEW2 视图约束校验脚本。

校验（对应全局只读规则）：
1. 源码约束：evolution_render.py 未 import LLM/模型/天气/数据库模块；
2. 幂等：同一 run_id 渲染两次输出完全一致；
3. 无副作用：渲染前后 run_records 目录无变化（不写存档、不发起调用）；
4. 与存档一致：视图中的 verdict/预测/历史窗口来自存档且未被修改；
5. 快照与页面一致：VIEW2_REPORT.md 生成后由 build_html.py 自检（本脚本校验 md 存在）。

用法（项目根目录）：
  python B07/VIEW/v2_evolution/evolution_check.py --run-id i3-20261031013638-f78ead
"""

import argparse
import hashlib
import sys
from pathlib import Path

VIEW_DIR = Path(__file__).resolve().parent
RECORDS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "B07" / "S5" / "run_records"

FORBIDDEN_IMPORTS = ("openai", "sklearn", "load_model", "get_weather", "fetch_forecast",
                     "predict_latest", "httpx", "b02_db", "query_series", "import llm")

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def snapshot_records():
    snap = {}
    for p in RECORDS_DIR.glob("*.json"):
        snap[p.name] = hashlib.md5(p.read_bytes()).hexdigest()
    return snap


def main():
    parser = argparse.ArgumentParser(description="VIEW2 视图约束校验")
    parser.add_argument("--run-id", required=True, help="校验渲染的 run_id")
    args = parser.parse_args()
    results = []

    # 1. 源码约束
    source = (VIEW_DIR / "evolution_render.py").read_text(encoding="utf-8")
    hits = [w for w in FORBIDDEN_IMPORTS if w in source]
    results.append(check("渲染器未 import LLM/模型/天气/数据库模块（只读无查询）",
                         not hits, "命中：%s" % (hits or "无")))

    # 2/3. 幂等 + 无副作用
    from evolution_render import build_view_data, load_run, render_md
    record = load_run(args.run_id)
    before = snapshot_records()
    text1 = render_md(build_view_data(record))
    text2 = render_md(build_view_data(record))
    results.append(check("渲染幂等：两次渲染输出完全一致", text1 == text2))
    after = snapshot_records()
    results.append(check("渲染无副作用：run_records 目录无新增/修改",
                         before == after, "%d files" % len(before)))

    # 4. 与存档一致
    e1 = next((e for e in record.get("adopted_evidence", [])
               if e.get("source_type") == "internal_history"), None)
    window = ((e1 or {}).get("result") or {}).get("window", "")
    verdict = (record.get("judgment") or {}).get("verdict", "")
    results.append(check("视图含存档历史窗口（未重新查询）",
                         window and window in text1, window))
    results.append(check("视图 verdict 与存档一致", verdict and verdict in text1, verdict))

    # 5. md 快照存在
    md_file = VIEW_DIR / "VIEW2_REPORT.md"
    results.append(check("VIEW2_REPORT.md 快照已生成", md_file.exists(),
                         str(md_file)))

    print("\nVIEW2 校验总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
