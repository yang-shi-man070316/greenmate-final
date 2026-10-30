"""创新点1拓展（同瞬时读数、不同历史时序）测试（无需 LLM Key / 无需联网）。

- 样本A 平台段注入：幂等、30±0.4 小幅波动、末点 30.0℃；
- 两组装载：当前观测几乎一致（≈30℃），历史曲线形态不同；
- 判定：A stable_trend_* vs B warming_trend_*，趋势与预测双维度区分；
- 报告生成（mock）与 run_id/存档。

运行：python B07/S2/tests/test_innovate1_ext.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
S2 = Path(__file__).resolve().parent.parent  # B07/S2
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT, S2):
    sys.path.insert(0, str(d))

from innovate1_ext import (judge, load_sample, make_run_id, prepare_plateau,  # noqa: E402
                           run_pipeline, save_run)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, detail=""):
    print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))
    return passed


def main():
    results = []

    # 1. 样本A 平台段注入（幂等）
    rows, injected = prepare_plateau()
    temps = [r["temperature"] for r in rows]
    results.append(check("平台段 7 点：30±0.4 小幅波动、末点 30.0℃",
                         len(rows) == 7 and abs(temps[-1] - 30.0) < 0.2
                         and max(temps) - min(temps) <= 0.8,
                         "%.1f~%.1f，末点 %.1f（injected=%s）" % (min(temps), max(temps), temps[-1], injected)))
    results.append(check("平台段注入幂等（重复调用不再追加）",
                         prepare_plateau()[1] is False))

    # 2. 两组装载与当前值一致性
    ca, ha, pa = load_sample("A")
    cb, hb, pb = load_sample("B")
    results.append(check("两组当前观测几乎一致（≈30℃）",
                         abs(ca["temperature"] - cb["temperature"]) <= 0.2
                         and abs(ca["temperature"] - 30.0) <= 0.5,
                         "A=%.1f℃ B=%.1f℃" % (ca["temperature"], cb["temperature"])))
    results.append(check("样本A 历史小幅波动（幅差≤0.8℃）",
                         max(r["temperature"] for r in ha) - min(r["temperature"] for r in ha) <= 0.8))
    results.append(check("样本B 历史匀速升温（25→30℃，幅差≥4℃）",
                         hb[0]["temperature"] < 26 and hb[-1]["temperature"] >= 29.5
                         and hb[-1]["temperature"] - hb[0]["temperature"] >= 4.0,
                         "%.1f→%.1f" % (hb[0]["temperature"], hb[-1]["temperature"])))
    results.append(check("两组均带 B06 预测（完整链路，不做消融）",
                         pa["predicted_attention"] in ("NORMAL", "WATCH")
                         and pb["predicted_attention"] in ("NORMAL", "WATCH")))

    # 3. 判定：唯一变量历史曲线 → verdict 不同
    ja = judge("A", ca, ha, pa)
    jb = judge("B", cb, hb, pb)
    results.append(check("样本A → stable_trend_prediction_*（历史平稳）",
                         ja["verdict"].startswith("stable_trend_prediction_"), ja["verdict"]))
    results.append(check("样本B → warming_trend_prediction_*（历史升温）",
                         jb["verdict"].startswith("warming_trend_prediction_"), jb["verdict"]))
    results.append(check("两组 verdict 不同（历史曲线决定状态判断）",
                         ja["verdict"] != jb["verdict"],
                         "%s vs %s" % (ja["verdict"], jb["verdict"])))
    results.append(check("趋势与预测严格区分（note 含『已发生』与『预测/推断』）",
                         "已发生" in ja["verdict_note"] and "预测" in ja["verdict_note"]
                         and "已发生" in jb["verdict_note"] and "预测" in jb["verdict_note"]))

    # 4. run_id 与存档
    rid = make_run_id()
    results.append(check("run_id 为 i1x- 前缀", bool(re.match(r"^i1x-\d{14}-[0-9a-f]{6}$", rid)), rid))
    record = {"run_id": rid, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "sample": "A", "experiment": "innovate1_ext",
              "current_observation": {k: ca[k] for k in ("timestamp", "temperature", "humidity", "light")},
              "history_samples": ha, "prediction": pa, "judgment": ja,
              "llm_explanation": {"status": "error", "error_type": "test", "message": "无 LLM"}}
    path = save_run(record)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    results.append(check("存档读写 roundtrip", loaded["run_id"] == rid
                         and loaded["judgment"]["verdict"] == ja["verdict"], str(path)))

    print("\n创新点1拓展 测试总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
