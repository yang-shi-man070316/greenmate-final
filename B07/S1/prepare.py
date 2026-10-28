"""S1 稳态数据集准备：让 B02 的最近 3 小时成为 29~30℃ 的稳定模拟时段。

复用 B02 模拟器（仅导入调用，不复制源码）：
- 从 B02 当前库尾连续追加样本到 TARGET_END（2026-10-20 16:30，白昼时段）；
- B02 基线规则（昼夜正弦）保证该时段温度 29~30℃ 小幅波动、湿度 45~47%、
  光照约 52000~55000 lux（正常白天），无持续升降；
- 追加段在 B02 扰动日历之外，sim_scenario 全部为 normal——不人为制造异常；
- 幂等：库尾已到达 TARGET_END 则跳过追加。

输出稳定性统计解释（为什么这段数据整体稳定）。
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in (ROOT / "B06", ROOT / "B05", ROOT / "B04", ROOT / "B03", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

from B02 import db as b02_db          # noqa: E402
from B02 import simulator as b02_sim  # noqa: E402

TARGET_END = "2026-10-20 16:30:00"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def ensure_stable_window(target_end=TARGET_END):
    """确保 B02 库尾到达 target_end（连续追加），返回 (最近6点稳态窗口, 稳定性统计)。"""
    conn = b02_db.connect()
    try:
        last = b02_db.query_last_timestamp(conn)
        if not last:
            raise RuntimeError("B02 库为空，请先运行 python B02/generate.py")
        target = datetime.strptime(target_end, "%Y-%m-%d %H:%M:%S")
        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        if last_dt >= target:
            print("[跳过] 库尾 %s 已到达目标 %s，无需追加" % (last, target_end))
        else:
            start_dt = last_dt + timedelta(minutes=b02_sim.SAMPLE_INTERVAL_MINUTES)
            n = int((target - start_dt).total_seconds() // (b02_sim.SAMPLE_INTERVAL_MINUTES * 60)) + 1
            rows = b02_sim.generate_samples(start_dt, n, seed=42)
            b02_db.insert_samples(conn, rows)
            print("[追加] 从 %s 连续追加 %d 条（B02 模拟器规则）→ 库尾 %s" % (
                start_dt.strftime("%Y-%m-%d %H:%M:%S"), n, rows[-1]["timestamp"]))
        all_rows = b02_db.query_series(conn)
    finally:
        conn.close()
    window = all_rows[-6:]  # 最近 3 小时（6 个采样点）
    stats = explain_stability(window)
    return window, stats


def explain_stability(window):
    """解释为什么这段数据整体稳定（统计证据 + 稳定判定规则）。"""
    if len(window) < 2:
        return {"stable": False, "explanation": "窗口样本不足"}
    temps = [p["temperature"] for p in window]
    hums = [p["humidity"] for p in window]
    lights = [p["light"] for p in window]
    half = len(window) // 2
    # 前后半均值差（两半各自求均值再相减；两半长度可能不等，必须按各自长度归一）
    slope_t = round((sum(temps[half:]) / len(temps[half:])) - (sum(temps[:half]) / len(temps[:half])), 2)
    slope_h = round((sum(hums[half:]) / len(hums[half:])) - (sum(hums[:half]) / len(hums[:half])), 2)
    scenarios = sorted(set(p["sim_scenario"] for p in window))
    sources = sorted(set(p["source_type"] for p in window))

    t_range = round(max(temps) - min(temps), 1)
    h_range = round(max(hums) - min(hums), 1)
    stable = (
        t_range <= 2.0 and abs(slope_t) <= 0.5          # 温度小幅波动、无持续升降
        and h_range <= 10.0 and abs(slope_h) <= 3.0     # 湿度窄幅、无持续升降
        and all(0 <= l <= 120000 for l in lights)       # 光照在合法范围
        and scenarios == ["normal"]                      # 无扰动
        and sources == ["SIMULATED"]                     # 模拟数据源
    )
    return {
        "window": "%s ~ %s" % (window[0]["timestamp"], window[-1]["timestamp"]),
        "temperature": {"min": round(min(temps), 1), "max": round(max(temps), 1),
                        "mean": round(sum(temps) / len(temps), 1), "range": t_range},
        "humidity": {"min": round(min(hums), 1), "max": round(max(hums), 1),
                     "mean": round(sum(hums) / len(hums), 1), "range": h_range},
        "light": {"min": round(min(lights)), "max": round(max(lights)),
                  "mean": round(sum(lights) / len(lights))},
        "temp_trend_c_per_3h": slope_t,
        "hum_trend_pct_per_3h": slope_h,
        "sim_scenarios": scenarios,
        "source_types": sources,
        "stable": stable,
        "explanation": (
            "温度 %.1f~%.1f℃ 小幅波动（幅差 %.1f℃），3 小时前后半均值差 %.2f℃（无持续升降）；"
            "湿度 %.1f~%.1f%% 窄幅波动（幅差 %.1f%%，前后半均值差 %.2f%%）；"
            "光照 %.0f~%.0f lux 为正常白天范围；"
            "全部样本 sim_scenario=normal（无扰动片段）、source_type=SIMULATED。"
            "综合判定：%s。" % (
                min(temps), max(temps), t_range, slope_t,
                min(hums), max(hums), h_range, slope_h,
                min(lights), max(lights),
                "整体稳定" if stable else "不满足稳定条件"))
    }


def main():
    window, stats = ensure_stable_window()
    print("[稳态窗口] %s" % stats["window"])
    print("[温度] min=%.1f max=%.1f mean=%.1f | [湿度] min=%.1f max=%.1f mean=%.1f | [光照] %.0f~%.0f lux" % (
        stats["temperature"]["min"], stats["temperature"]["max"], stats["temperature"]["mean"],
        stats["humidity"]["min"], stats["humidity"]["max"], stats["humidity"]["mean"],
        stats["light"]["min"], stats["light"]["max"]))
    print("[趋势] 温度前后半均值差 %s℃ | 湿度前后半均值差 %s%% | scenarios=%s" % (
        stats["temp_trend_c_per_3h"], stats["hum_trend_pct_per_3h"], stats["sim_scenarios"]))
    print("[解释] %s" % stats["explanation"])


if __name__ == "__main__":
    main()
