"""VIEW4 视图约束校验脚本。

校验（对应全局只读规则）：
1. 源码约束：compare_render.py 未 import LLM/模型/接口/数据库模块；
2. 幂等：渲染两次输出完全一致；
3. 无副作用：渲染前后所有 run_records 目录无变化；
4. 存档只读：三组对照的 run_id 与 verdict 来自存档且未被修改；
5. 每组对照四要素齐全（输入变化/证据变化/状态结果/原因解释）。

用法（项目根目录）：
  python B07/VIEW/v4_compare/compare_check.py
"""

import hashlib
import sys
from pathlib import Path

VIEW_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parent.parent.parent.parent
RECORDS_DIRS = [ROOT / "B07" / ("S%d" % i) / "run_records" for i in range(1, 6)]

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
        if not d.exists():
            continue
        for p in d.glob("*.json"):
            snap[str(p)] = hashlib.md5(p.read_bytes()).hexdigest()
    return snap


def main():
    results = []

    source = (VIEW_DIR / "compare_render.py").read_text(encoding="utf-8")
    hits = [w for w in FORBIDDEN_IMPORTS if w in source]
    results.append(check("渲染器未 import LLM/模型/接口/数据库模块（纯 json 只读）",
                         not hits, "命中：%s" % (hits or "无")))

    from compare_render import PAIRS, load_scene, render_md
    before = snapshot()
    pairs = [fn() for fn in PAIRS]
    pairs = [p for p in pairs if p]
    text1 = render_md(pairs)
    text2 = render_md(pairs)
    results.append(check("渲染幂等：两次渲染输出完全一致", text1 == text2))
    after = snapshot()
    results.append(check("渲染无副作用：所有 run_records 目录无变化",
                         before == after, "%d files" % len(before)))

    results.append(check("三组核心对照均加载到真实存档", len(pairs) == 3,
                         "实际 %d 组" % len(pairs)))
    for p in pairs:
        results.append(check("对照%d 四要素齐全（输入/证据/状态/原因）" % p["id"],
                             all(p[k] for k in ("input_change", "evidence_change",
                                                 "state_change", "reason")),
                             "%s ↔ %s" % (p["a"]["scene"], p["b"]["scene"])))
        results.append(check("对照%d run_id/verdict 来自存档且出现在视图中" % p["id"],
                             p["a"]["run_id"] in text1 and p["b"]["run_id"] in text1
                             and p["a"]["verdict"] in text1 and p["b"]["verdict"] in text1,
                             "%s=%s / %s=%s" % (p["a"]["run_id"], p["a"]["verdict"],
                                                p["b"]["run_id"], p["b"]["verdict"])))

    print("\nVIEW4 校验总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
