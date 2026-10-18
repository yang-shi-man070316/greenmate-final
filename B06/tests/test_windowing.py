"""窗口化单测（无需 LLM / 无需联网）：窗口数、时段、可回溯、可改 window_size。

运行：python B06/tests/test_windowing.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B06 目录
sys.path.insert(0, str(ROOT))

import windowing  # noqa: E402
from features import extract_features  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    results = []

    def check(name, passed, detail=""):
        results.append(passed)
        print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))

    samples = windowing.load_b02_samples()
    check("B02 7 天样本加载（应为 336 条）", len(samples) == 336,
          "实际 %d 条" % len(samples))
    check("样本按 timestamp 升序", all(
        samples[i]["timestamp"] <= samples[i + 1]["timestamp"]
        for i in range(len(samples) - 1)))

    windows = windowing.build_windows(samples, window_size=6, prediction_horizon=4)
    check("默认窗口数（336-6-4+1=327）", len(windows) == 327, "实际 %d" % len(windows))
    first, last = windows[0], windows[-1]
    check("首窗口时段正确", first["window_start"] == "2026-10-07 00:00:00"
          and first["window_end"] == "2026-10-07 02:30:00"
          and first["predict_start"] == "2026-10-07 03:00:00"
          and first["predict_end"] == "2026-10-07 04:30:00",
          "%s~%s → %s~%s" % (first["window_start"], first["window_end"],
                             first["predict_start"], first["predict_end"]))
    check("末窗口预测终点=数据集终点", last["predict_end"] == "2026-10-13 23:30:00",
          last["predict_end"])
    check("输入窗口 6 点 / 预测窗口 4 点", len(first["input_points"]) == 6
          and len(first["prediction_points"]) == 4)

    # 可回溯：随机取一个窗口，按时段从 B02 重查并重算特征，应与生成时一致
    w = windows[123]
    pts_in, pts_out, feats_back = windowing.traceback_to_b02(w)
    feats_gen = extract_features(w["input_points"])
    check("窗口可回溯 B02 时段并重算一致", feats_back == feats_gen,
          "window=%s~%s" % (w["window_start"], w["window_end"]))

    # 可修改 window_size 重新生成
    windows12 = windowing.build_windows(samples, window_size=12, prediction_horizon=4)
    check("window_size=12 重新生成（336-12-4+1=321）", len(windows12) == 321,
          "实际 %d" % len(windows12))
    windows_h2 = windowing.build_windows(samples, window_size=6, prediction_horizon=2)
    check("prediction_horizon=2 重新生成（336-6-2+1=329）", len(windows_h2) == 329,
          "实际 %d" % len(windows_h2))

    try:
        windowing.build_windows(samples, window_size=6, prediction_horizon=9)
        check("非法 horizon 被拒绝", False, "9 未被拒绝")
    except ValueError:
        check("非法 horizon 被拒绝", True)

    print("\n窗口化单测总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
