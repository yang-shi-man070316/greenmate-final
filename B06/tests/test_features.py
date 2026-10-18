"""特征/标签单测（无需 LLM / 无需联网）：
- 8 个骨架特征白名单；
- 特征值手工验证（current/mean/delta 计算正确）；
- 禁止混入：sim_scenario、label_source、timestamp、B03 天气等字段不在特征中；
- 标签透明规则：基线不触发、扰动触发。

运行：python B06/tests/test_features.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B06 目录
sys.path.insert(0, str(ROOT))

from features import FEATURE_NAMES, extract_features  # noqa: E402
from labeling import label_prediction_window  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    results = []

    def check(name, passed, detail=""):
        results.append(passed)
        print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))

    # 1. 特征白名单
    check("特征共 8 个且为骨架定义", len(FEATURE_NAMES) == 8
          and FEATURE_NAMES == ["temp_current", "hum_current", "light_current",
                                "temp_mean", "hum_mean", "light_mean",
                                "temp_delta", "hum_delta"],
          str(FEATURE_NAMES))

    # 2. 特征值手工验证
    pts = [
        {"timestamp": "2026-10-07 00:00:00", "temperature": 10.0, "humidity": 50.0, "light": 5.0},
        {"timestamp": "2026-10-07 00:30:00", "temperature": 11.0, "humidity": 51.0, "light": 5.0},
        {"timestamp": "2026-10-07 01:00:00", "temperature": 12.0, "humidity": 52.0, "light": 5.0},
        {"timestamp": "2026-10-07 01:30:00", "temperature": 13.0, "humidity": 53.0, "light": 5.0},
        {"timestamp": "2026-10-07 02:00:00", "temperature": 14.0, "humidity": 54.0, "light": 5.0},
        {"timestamp": "2026-10-07 02:30:00", "temperature": 15.0, "humidity": 55.0, "light": 6.0},
    ]
    f = extract_features(pts)
    check("current 特征正确（最后点）",
          f["temp_current"] == 15.0 and f["hum_current"] == 55.0 and f["light_current"] == 6.0)
    check("mean 特征正确（窗口均值）",
          f["temp_mean"] == 12.5 and f["hum_mean"] == 52.5 and f["light_mean"] == 5.17)
    check("delta 特征正确（末-首）",
          f["temp_delta"] == 5.0 and f["hum_delta"] == 5.0)
    check("特征键恰好 8 个（无多余字段混入）", set(f.keys()) == set(FEATURE_NAMES),
          str(sorted(f.keys())))

    # 3. 禁止混入字段（特征键不含任何元数据/原始扩展字段）
    forbidden = ("sim_scenario", "label_source", "source_type", "timestamp",
                 "weather", "retrieved_at", "state_id")
    check("sim_scenario/label_source/天气等未混入特征键",
          not any(k in f for k in forbidden))

    # 4. 标签透明规则：基线不触发，扰动触发
    base = [
        {"timestamp": "2026-10-07 12:00:00", "temperature": 29.0, "humidity": 50.0, "light": 50000.0},
        {"timestamp": "2026-10-07 12:30:00", "temperature": 29.5, "humidity": 49.0, "light": 54000.0},
        {"timestamp": "2026-10-07 13:00:00", "temperature": 30.0, "humidity": 48.0, "light": 55000.0},
        {"timestamp": "2026-10-07 13:30:00", "temperature": 29.0, "humidity": 50.0, "light": 50000.0},
    ]
    check("基线时段标签=NORMAL", label_prediction_window(base)[0] == "NORMAL",
          str(label_prediction_window(base)))
    heat = [
        {"timestamp": "2026-10-08 14:00:00", "temperature": 36.0, "humidity": 35.0, "light": 60000.0},
        {"timestamp": "2026-10-08 14:30:00", "temperature": 37.5, "humidity": 33.0, "light": 61000.0},
        {"timestamp": "2026-10-08 15:00:00", "temperature": 38.0, "humidity": 30.0, "light": 60500.0},
        {"timestamp": "2026-10-08 15:30:00", "temperature": 36.5, "humidity": 32.0, "light": 58000.0},
    ]
    label, src = label_prediction_window(heat)
    check("热浪时段标签=WATCH", label == "WATCH", str((label, src)))
    check("label_source 记录触发规则", "temp_high" in src and "hum_low" in src, src)
    night = [
        {"timestamp": "2026-10-11 22:00:00", "temperature": 16.0, "humidity": 60.0, "light": 8000.0},
        {"timestamp": "2026-10-11 22:30:00", "temperature": 16.0, "humidity": 60.0, "light": 8000.0},
        {"timestamp": "2026-10-11 23:00:00", "temperature": 16.0, "humidity": 60.0, "light": 8000.0},
        {"timestamp": "2026-10-11 23:30:00", "temperature": 16.0, "humidity": 60.0, "light": 8000.0},
    ]
    label, src = label_prediction_window(night)
    check("夜间强光标签=WATCH（light_night）", label == "WATCH" and "light_night" in src,
          str((label, src)))

    print("\n特征/标签单测总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
