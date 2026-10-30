"""VIEW1 视图约束校验脚本。

校验四项（对应任务全局规则）：
1. 源码约束：overview_render.py 未 import LLM/模型/天气模块，render 为纯函数；
2. 幂等：同一 run_id 渲染两次输出完全一致（刷新/重开视图不产生变化）；
3. 与存档一致：视图中的 verdict/预测/趋势等字段与存档原始值一致（只读透传，不重算）；
4. 无副作用：渲染前后 run_records 目录文件列表与大小无变化（不写存档、不发起调用）。

用法（项目根目录）：
  python B07/VIEW/v1_overview/overview_check.py --run-id i3-20261031013638-f78ead
"""

import argparse
import hashlib
import sys
from pathlib import Path

VIEW_DIR = Path(__file__).resolve().parent
RECORDS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "B07" / "S5" / "run_records"

FORBIDDEN_IMPORTS = ("openai", "sklearn", "load_model", "get_weather", "fetch_forecast",
                     "predict_latest", "httpx", "llm")

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def snapshot_records():
    """run_records 目录快照（文件名 → 内容哈希），用于副作用检测。"""
    snap = {}
    for p in RECORDS_DIR.glob("*.json"):
        snap[p.name] = hashlib.md5(p.read_bytes()).hexdigest()
    return snap


def main():
    parser = argparse.ArgumentParser(description="VIEW1 视图约束校验")
    parser.add_argument("--run-id", required=True, help="校验渲染的 run_id")
    args = parser.parse_args()
    results = []

    # 1. 源码约束
    source = (VIEW_DIR / "overview_render.py").read_text(encoding="utf-8")
    hits = [w for w in FORBIDDEN_IMPORTS if w in source]
    results.append(check("渲染器未 import LLM/模型/天气模块（只读无调用）",
                         not hits, "命中：%s" % (hits or "无")))

    # 2/3/4. 运行时：渲染两次对比 + 与存档一致 + 无副作用
    from overview_render import load_run, render
    record = load_run(args.run_id)
    before = snapshot_records()

    text1 = render(record)
    text2 = render(record)  # 模拟"刷新/重开视图"
    results.append(check("渲染幂等：两次渲染输出完全一致（刷新视图结论不变）",
                         text1 == text2))
    after = snapshot_records()
    results.append(check("渲染无副作用：run_records 目录无新增/修改",
                         before == after,
                         "before=%d files after=%d files" % (len(before), len(after))))

    # 与存档一致（关键字段只读透传）
    judgment = record.get("judgment") or {}
    e2 = next((e for e in record.get("adopted_evidence", [])
               if e.get("source_type") == "ml_prediction"), None)
    verdict = judgment.get("verdict", "—")
    pred = ((e2 or {}).get("result") or {}).get("predicted_attention", "—")
    results.append(check("视图 verdict 与存档一致（未重算）",
                         verdict and verdict in text1, "verdict=%s" % verdict))
    results.append(check("视图预测与存档一致（未重跑模型）",
                         pred and pred in text1, "pred=%s" % pred))
    results.append(check("视图顶部标注 run_id",
                         args.run_id in text1))

    print("\nVIEW1 校验总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
