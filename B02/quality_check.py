"""数据质量检查：空值 / 重复 / 异常范围 / 时间连续性 / 扰动分布。

运行（项目根目录）：python B02/quality_check.py
输出：控制台逐项 PASS/FAIL + docs/quality_report.md
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from simulator import DISTURBANCES, RANGES, SAMPLE_INTERVAL_MINUTES, TOTAL_SAMPLES  # noqa: E402

DOCS_DIR = ROOT / "docs"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    conn = db.connect()
    results = []  # (name, passed, detail)
    per_d = {}
    try:
        def check(name, passed, detail):
            results.append((name, passed, detail))
            print("[%s] %s — %s" % ("PASS" if passed else "FAIL", name, detail))

        total = db.count_samples(conn)
        check("样本总量", total >= TOTAL_SAMPLES,
              "当前 %d 条（基准 336，允许追加后更多）" % total)

        nulls = conn.execute(
            "SELECT COUNT(*) AS n FROM environment_samples "
            "WHERE timestamp IS NULL OR temperature IS NULL OR humidity IS NULL OR light IS NULL"
        ).fetchone()["n"]
        check("空值检查", nulls == 0, "空值样本 %d 条" % nulls)

        dup = conn.execute(
            "SELECT COUNT(*) - COUNT(DISTINCT timestamp) AS n FROM environment_samples"
        ).fetchone()["n"]
        check("重复数据检查", dup == 0, "重复 timestamp %d 条（UNIQUE 约束兜底）" % dup)

        for f, (lo, hi) in RANGES.items():
            out = conn.execute(
                "SELECT COUNT(*) AS n FROM environment_samples WHERE %s < ? OR %s > ?" % (f, f),
                (lo, hi),
            ).fetchone()["n"]
            r = conn.execute(
                "SELECT MIN(%s) AS lo, MAX(%s) AS hi FROM environment_samples" % (f, f)
            ).fetchone()
            check("范围检查: %s" % f, out == 0,
                  "实测 [%s, %s]，合法 [%s, %s]，越界 %d 条" % (r["lo"], r["hi"], lo, hi, out))

        rows = conn.execute("SELECT timestamp FROM environment_samples ORDER BY timestamp").fetchall()
        gaps = 0
        for i in range(1, len(rows)):
            t0 = datetime.strptime(rows[i - 1]["timestamp"], "%Y-%m-%d %H:%M:%S")
            t1 = datetime.strptime(rows[i]["timestamp"], "%Y-%m-%d %H:%M:%S")
            if t1 - t0 != timedelta(minutes=SAMPLE_INTERVAL_MINUTES):
                gaps += 1
        check("时间连续性", gaps == 0,
              "相邻采样间隔非 %d 分钟的断点 %d 处（%d 条样本）" % (SAMPLE_INTERVAL_MINUTES, gaps, len(rows)))

        nd = conn.execute("SELECT COUNT(*) AS n FROM disturbance_events").fetchone()["n"]
        check("扰动数量", 4 <= nd <= 6, "扰动片段 %d 个（要求 4~6）" % nd)

        dates = set()
        for r in conn.execute("SELECT start_ts, end_ts FROM disturbance_events"):
            dates.add(r["start_ts"][:10])
            dates.add(r["end_ts"][:10])
        check("扰动分散度", len(dates) >= 4,
              "扰动覆盖 %d 个不同日期：%s" % (len(dates), ", ".join(sorted(dates))))

        normal_ratio = conn.execute(
            "SELECT CAST(SUM(CASE WHEN sim_scenario='normal' THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS r "
            "FROM environment_samples"
        ).fetchone()["r"]
        check("正常样本占比", normal_ratio > 0.5,
              "sim_scenario='normal' 占比 %.1f%%" % (normal_ratio * 100))

        for r in conn.execute("SELECT sim_scenario, COUNT(*) AS n FROM environment_samples GROUP BY sim_scenario"):
            per_d[r["sim_scenario"]] = r["n"]
        missing = [d["id"] for d in DISTURBANCES if not any(k.startswith(d["id"]) for k in per_d)]
        check("各扰动均有样本", not missing,
              "缺失扰动的样本: %s；分布: %s" % (missing or "无", per_d))
    finally:
        conn.close()

    passed_all = all(p for _, p, _ in results)
    print("\n质量检查总结论：%s" % ("全部通过 ✅" if passed_all else "存在未通过项 ❌"))

    # 写报告
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# GreenMate B02 数据质量检查报告",
        "",
        "- 时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 数据库：%s" % db.DB_PATH,
        "- 结论：%s" % ("全部通过 ✅" if passed_all else "存在未通过项 ❌"),
        "",
        "| 检查项 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, passed, detail in results:
        lines.append("| %s | %s | %s |" % (name, "✅" if passed else "❌", detail))
    (DOCS_DIR / "quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("报告已写入：docs/quality_report.md")
    return 0 if passed_all else 1


if __name__ == "__main__":
    sys.exit(main())
