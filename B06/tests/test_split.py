"""时间切分单测（无需 LLM / 无需联网）：
- 前 5 天训练、后 2 天测试；
- 训练/测试时间不重叠（无时间泄露）；
- 跨边界预测窗口被丢弃；
- 训练集与测试集都包含 NORMAL 与 WATCH。

运行：python B06/tests/test_split.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # B06 目录
sys.path.insert(0, str(ROOT))

from dataset import TRAIN_END, build_dataset, split_train_test  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    results = []

    def check(name, passed, detail=""):
        results.append(passed)
        print("[%s] %s %s" % ("PASS" if passed else "FAIL", name, detail))

    rows = build_dataset(6, 4)
    train, test, dropped = split_train_test(rows, TRAIN_END)

    check("训练+测试+丢弃 == 总样本", len(train) + len(test) + len(dropped) == len(rows),
          "%d+%d+%d vs %d" % (len(train), len(test), len(dropped), len(rows)))
    check("训练集全部早于边界（predict_end < %s）" % TRAIN_END,
          all(r["predict_end"] < TRAIN_END for r in train))
    check("测试集全部不早于边界（predict_start >= %s）" % TRAIN_END,
          all(r["predict_start"] >= TRAIN_END for r in test))
    train_max = max(r["predict_end"] for r in train)
    test_min = min(r["predict_start"] for r in test)
    check("训练/测试时间不重叠（无时间泄露）", train_max < test_min,
          "训练最晚 %s < 测试最早 %s" % (train_max, test_min))
    check("跨边界窗口被丢弃", len(dropped) > 0 and all(
        r["predict_start"] < TRAIN_END <= r["predict_end"] or
        r["window_end"] < TRAIN_END <= r["predict_end"]
        for r in dropped), "丢弃 %d 个" % len(dropped))
    labels_train = set(r["label"] for r in train)
    labels_test = set(r["label"] for r in test)
    check("训练集含 NORMAL 与 WATCH", labels_train == {"NORMAL", "WATCH"}, str(labels_train))
    check("测试集含 NORMAL 与 WATCH", labels_test == {"NORMAL", "WATCH"}, str(labels_test))

    # 丢弃窗口全部是"预测窗口跨越边界"的样本（人工抽查第一个）
    if dropped:
        d = dropped[0]
        check("丢弃样本抽查：预测窗口跨越边界",
              d["predict_start"] < TRAIN_END <= d["predict_end"],
              "%s ~ %s" % (d["predict_start"], d["predict_end"]))

    print("\n时间切分单测总结论：%s" % ("全部通过 ✅" if all(results) else "存在未通过项 ❌"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
