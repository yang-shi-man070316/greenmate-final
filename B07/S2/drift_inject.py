"""S2 漂移场景数据注入：仅修改 B02 历史时序数据（追加漂移段），不动任何模块逻辑。

漂移段：7 个采样点（3 小时），温度从 25.0℃ 匀速渐进升温至 30.0℃
（每 30 分钟 +0.833℃）；湿度 50.0→47.3% 微降；光照按傍晚回落过程（12000→10 lux）；
sim_scenario=normal、source_type=SIMULATED。

当前时刻（段尾）≈30.0℃，与 S1 基线（≈30.4℃）几乎一致——两组瞬时值相同，
仅历史演化过程不同（S1 稳定 29~30℃ vs S2 持续升温漂移）。

幂等：库尾最后 7 点已是漂移形态（首≈25℃、尾≈30℃、升幅≥4℃）则跳过；
否则从库尾 +30 分钟起追加新漂移段（时间顺延，不影响实验对照）。
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B02 import db as b02_db  # noqa: E402

DRIFT_TEMPS = [25.0, 25.8, 26.7, 27.5, 28.3, 29.2, 30.0]
DRIFT_HUMS = [50.0, 49.6, 49.1, 48.7, 48.2, 47.8, 47.3]
DRIFT_LIGHTS = [12000.0, 9000.0, 6000.0, 3500.0, 1500.0, 400.0, 10.0]

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def is_drift_injected(conn):
    """检测库尾最后 7 点是否已是漂移形态（幂等判断）。"""
    rows = b02_db.query_series(conn)
    if len(rows) < 7:
        return False
    temps = [r["temperature"] for r in rows[-7:]]
    return (abs(temps[0] - DRIFT_TEMPS[0]) < 0.5
            and abs(temps[-1] - DRIFT_TEMPS[-1]) < 0.5
            and temps[-1] - temps[0] >= 4.0)


def inject_drift():
    """向 B02 库尾追加漂移段，返回 (是否新注入, 漂移段样本)。"""
    conn = b02_db.connect()
    try:
        if is_drift_injected(conn):
            rows = b02_db.query_series(conn)[-7:]
            print("[跳过] 库尾已是漂移段（%s ~ %s），无需重复注入" % (
                rows[0]["timestamp"], rows[-1]["timestamp"]))
            return False, rows
        last = b02_db.query_last_timestamp(conn)
        if not last:
            raise RuntimeError("B02 库为空，请先运行 python B02/generate.py")
        start_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S") + timedelta(minutes=30)
        rows = []
        for i in range(len(DRIFT_TEMPS)):
            ts = start_dt + timedelta(minutes=30 * i)
            rows.append({
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "temperature": DRIFT_TEMPS[i],
                "humidity": DRIFT_HUMS[i],
                "light": DRIFT_LIGHTS[i],
                "source_type": "SIMULATED",
                "sim_scenario": "normal",
            })
        b02_db.insert_samples(conn, rows)
        print("[注入] 漂移段 %s ~ %s：温度 %.1f → %.1f℃ 匀速升温（7 点），湿度 %.1f→%.1f%%，光照 %.0f→%.0f lux" % (
            rows[0]["timestamp"], rows[-1]["timestamp"],
            rows[0]["temperature"], rows[-1]["temperature"],
            rows[0]["humidity"], rows[-1]["humidity"],
            rows[0]["light"], rows[-1]["light"]))
        return True, rows
    finally:
        conn.close()


def main():
    inject_drift()


if __name__ == "__main__":
    main()
