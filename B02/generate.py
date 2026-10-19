"""一键生成 7 天 336 条模拟数据并持久化到 SQLite。

用法（项目根目录）：
  python B02/generate.py             # 生成（库已非空时提示 --fresh / --append）
  python B02/generate.py --fresh     # 清空数据库后重新生成
  python B02/generate.py --append 4  # 在库末尾追加 4 小时（8 个采样点）
  python B02/generate.py --seed 42   # 固定随机种子（默认 42，可复现）
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from simulator import (  # noqa: E402
    DEFAULT_END, DEFAULT_SEED, DISTURBANCES, SAMPLE_INTERVAL_MINUTES,
    TOTAL_SAMPLES, generate_samples, generate_timeline,
)

DOCS_DIR = ROOT / "docs"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="GreenMate B02 模拟数据生成")
    parser.add_argument("--fresh", action="store_true", help="清空数据库后重新生成")
    parser.add_argument("--append", type=float, metavar="HOURS", help="在库末尾追加 N 小时新样本")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子（默认 42）")
    parser.add_argument("--end", type=str, default=None, metavar="'YYYY-MM-DD HH:MM'",
                        help="时间轴终点（默认 2026-10-14 00:00；与 --fresh 配合使用。"
                             "注意：更换时间轴后 B06 的固定数据集窗口需同步更新）")
    args = parser.parse_args()

    conn = db.connect()
    try:
        db.init_db(conn)

        if args.append:
            last = db.query_last_timestamp(conn)
            if not last:
                print("[错误] 库为空，无法追加；请先运行 generate.py 生成初始数据")
                sys.exit(1)
            start_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S") + timedelta(minutes=SAMPLE_INTERVAL_MINUTES)
            n = int(args.append * 60 / SAMPLE_INTERVAL_MINUTES)
            rows = generate_samples(start_dt, n, seed=args.seed)
            db.insert_samples(conn, rows)
            print("[追加] 从 %s 起追加 %.1f 小时，共 %d 条新样本" % (last, args.append, len(rows)))
        else:
            if db.count_samples(conn) > 0 and not args.fresh:
                print("[跳过] 库中已有 %d 条记录；如需重建请加 --fresh，如需继续追加请用 --append N"
                      % db.count_samples(conn))
                sys.exit(0)
            if args.fresh:
                conn.execute("DELETE FROM environment_samples")
                conn.execute("DELETE FROM disturbance_events")
                conn.commit()
                print("[重建] 已清空旧数据")
            end_dt = DEFAULT_END
            if args.end:
                try:
                    end_dt = datetime.strptime(args.end, "%Y-%m-%d %H:%M")
                except ValueError:
                    print("[错误] --end 格式应为 'YYYY-MM-DD HH:MM'（如 2026-10-20 00:00）")
                    sys.exit(1)
            rows = generate_timeline(end=end_dt, seed=args.seed)
            db.insert_samples(conn, rows)
            db.insert_disturbances(conn, DISTURBANCES)
            print("[生成] 采样间隔 %d 分钟 × 7 天 = %d 条，时间轴终点 %s，已写入并 commit"
                  % (SAMPLE_INTERVAL_MINUTES, TOTAL_SAMPLES, end_dt.strftime("%Y-%m-%d %H:%M")))

        count = db.count_samples(conn)
        first = conn.execute("SELECT MIN(timestamp) AS t FROM environment_samples").fetchone()["t"]
        last = db.query_last_timestamp(conn)
        print("[完成] 数据库: %s" % db.DB_PATH)
        print("[完成] 总样本: %d | 时间范围: %s ~ %s" % (count, first, last))
    finally:
        conn.close()

    # 扰动清单（机器可读，B06 复用）
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset": "greenmate_b02",
        "sample_interval_minutes": SAMPLE_INTERVAL_MINUTES,
        "days": 7,
        "expected_samples": TOTAL_SAMPLES,
        "seed": args.seed,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": "sim_scenario 仅为模拟器元数据，不作为标签",
        "disturbances": [
            {"id": d["id"], "type": d["type"],
             "start": d["start"].strftime("%Y-%m-%d %H:%M:%S"),
             "end": d["end"].strftime("%Y-%m-%d %H:%M:%S"),
             "description": d["description"], "ramp_samples": 2}
            for d in DISTURBANCES
        ],
    }
    (DOCS_DIR / "disturbances.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[清单] 已写入 docs/disturbances.json")


if __name__ == "__main__":
    main()
