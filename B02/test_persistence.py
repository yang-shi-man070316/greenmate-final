"""持久化验证：模拟「完全关闭程序再重启」，验证 SQLite 记录仍在、新样本可追加。

用法（项目根目录）：
  python B02/test_persistence.py --phase1   # 生成后：记录现状，打印重启指引
  （完全关闭后端程序，再重新启动）
  python B02/test_persistence.py --phase2   # 重启后：新连接验证旧记录仍存在
  python B02/test_persistence.py --append 4 # 追加 4 小时，验证新样本可继续追加

验证要点：每次查询都是全新连接（关闭旧连接再打开），与程序完全退出再启动等效；
数据存在 SQLite 文件中，与进程无关。
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from simulator import SAMPLE_INTERVAL_MINUTES, generate_samples  # noqa: E402

STATE_FILE = ROOT / "data" / ".phase1_state.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def snapshot(conn):
    """当前库状态快照（用于重启前后对比）。"""
    n = db.count_samples(conn)
    head = [dict(r) for r in conn.execute(
        "SELECT timestamp, temperature, humidity, light FROM environment_samples "
        "ORDER BY timestamp LIMIT 3").fetchall()]
    tail = [dict(r) for r in conn.execute(
        "SELECT timestamp, temperature, humidity, light FROM environment_samples "
        "ORDER BY timestamp DESC LIMIT 3").fetchall()]
    last = db.query_last_timestamp(conn)
    return {"count": n, "head": head, "tail": tail, "last": last}


def phase1():
    print("== Phase 1：生成后现状（独立连接） ==")
    conn = db.connect()
    try:
        snap = snapshot(conn)
    finally:
        conn.close()  # 关闭连接，模拟程序退出
    print("总样本: %d" % snap["count"])
    print("最早 3 条: %s" % json.dumps(snap["head"], ensure_ascii=False))
    print("最晚 3 条: %s" % json.dumps(snap["tail"], ensure_ascii=False))
    print("最后时间点: %s" % snap["last"])
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n请现在【完全关闭后端程序】（停止 uvicorn / 关闭终端），再重新启动，")
    print("然后运行：python B02/test_persistence.py --phase2")
    print("（或直接刷新 http://127.0.0.1:8000/B02 页面核对数据仍在）")


def phase2():
    print("== Phase 2：重启后验证（全新连接） ==")
    conn = db.connect()  # 全新连接，等价于重启后的新进程
    try:
        snap = snapshot(conn)
    finally:
        conn.close()
    print("总样本: %d" % snap["count"])
    print("最早 3 条: %s" % json.dumps(snap["head"], ensure_ascii=False))
    print("最晚 3 条: %s" % json.dumps(snap["tail"], ensure_ascii=False))
    print("最后时间点: %s" % snap["last"])

    if not STATE_FILE.exists():
        print("[提示] 未找到 phase1 快照，跳过自动对比（数据已能查询即说明持久化成功）")
        return 0
    before = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    ok = (before["count"] == snap["count"]
          and before["head"] == snap["head"]
          and before["tail"] == snap["tail"]
          and before["last"] == snap["last"])
    print("\n重启前后对比：%s" % ("完全一致 ✅（旧记录持久保存）" if ok else "不一致 ❌"))
    return 0 if ok else 1


def append(hours):
    print("== 追加测试：继续追加 %.1f 小时新样本 ==" % hours)
    conn = db.connect()
    try:
        db.init_db(conn)
        before = db.query_last_timestamp(conn)
        before_count = db.count_samples(conn)
        if not before:
            print("[错误] 库为空，请先运行 generate.py")
            sys.exit(1)
        start_dt = datetime.strptime(before, "%Y-%m-%d %H:%M:%S") + timedelta(minutes=SAMPLE_INTERVAL_MINUTES)
        n = int(hours * 60 / SAMPLE_INTERVAL_MINUTES)
        rows = generate_samples(start_dt, n)
        db.insert_samples(conn, rows)
        print("已追加 %d 条并 commit（%s → %s）" % (n, before, rows[-1]["timestamp"]))
    finally:
        conn.close()

    conn = db.connect()  # 全新连接复核
    try:
        after_count = db.count_samples(conn)
        last = db.query_last_timestamp(conn)
        rows = conn.execute("SELECT timestamp FROM environment_samples ORDER BY timestamp").fetchall()
        gaps = 0
        for i in range(1, len(rows)):
            t0 = datetime.strptime(rows[i - 1]["timestamp"], "%Y-%m-%d %H:%M:%S")
            t1 = datetime.strptime(rows[i]["timestamp"], "%Y-%m-%d %H:%M:%S")
            if t1 - t0 != timedelta(minutes=SAMPLE_INTERVAL_MINUTES):
                gaps += 1
    finally:
        conn.close()
    ok = after_count == before_count + n and gaps == 0
    print("复核（全新连接）：总数 %d → %d（+%d），时间连续性断点 %d 处" % (before_count, after_count, after_count - before_count, gaps))
    print("追加结论：%s" % ("通过 ✅（新样本可继续追加，timestamp 顺序正确）" if ok else "失败 ❌"))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description="GreenMate B02 持久化验证")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--phase1", action="store_true", help="生成后记录现状")
    group.add_argument("--phase2", action="store_true", help="重启后验证")
    group.add_argument("--append", type=float, metavar="HOURS", help="追加 N 小时新样本")
    args = parser.parse_args()

    if args.phase1:
        return phase1()
    if args.phase2:
        return phase2()
    return append(args.append)


if __name__ == "__main__":
    sys.exit(main())
