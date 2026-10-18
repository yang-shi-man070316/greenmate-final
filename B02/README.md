# GreenMate B02 · 数据记忆

把 B01 的「内存状态」升级为**可持久化查询的历史数据**：7 天 × 30 分钟 = 336 个采样点写入 SQLite，程序完全关闭再重启，旧记录仍然存在，新样本可以继续追加。

- 技术栈：SQL + SQLite + timestamp + source_type + Chart.js（无 ML / RAG / 真实传感器）
- 访问地址：http://127.0.0.1:8000/B02（B01 原页面仍在 http://127.0.0.1:8000/，B01 代码零改动）
- 边界：sim_scenario 只做模拟器元数据，**不作为标签**

## 快速开始（项目根目录）

```bash
# 1. 生成 7 天 336 条模拟数据并写入 SQLite（commit 落盘）
python B02/generate.py

# 2. 质量检查（空值/重复/范围/连续性/扰动分布）
python B02/quality_check.py

# 3. 启动（一个进程同时提供 B01 与 B02）
python B02/main.py

# 4. 浏览器打开 http://127.0.0.1:8000/B02
```

> 重建：`python B02/generate.py --fresh`；追加：`python B02/generate.py --append 4`

## 目录结构

```
B02/
├── main.py              # 组合启动入口（挂载 B01 于 /，B02 于 /B02）
├── app.py               # B02 FastAPI 子应用（查询 API + 页面）
├── simulator.py         # 7 天模拟器：昼夜基线 + 扰动 + 过渡 + 噪声（seed 可复现）
├── db.py                # SQLite 层：建表、写入、commit、查询
├── generate.py          # 一键生成 / 重建 / 追加
├── quality_check.py     # 质量校验并输出报告
├── test_persistence.py  # 重启持久化验证（--phase1 / --phase2 / --append）
├── static/              # 页面 + 本地 Chart.js（无 CDN 依赖）
├── data/
│   └── greenmate_b02.db # SQLite 数据库（持久化资产，重启不丢）
└── docs/
    ├── SCHEMA.md        # 数据资产：Schema、规则、扰动清单、统计、B06 复用说明
    ├── quality_report.md# 质量检查报告（自动生成）
    └── disturbances.json# 扰动清单（机器可读）
```

## 数据库 Schema

```sql
CREATE TABLE environment_samples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL UNIQUE,           -- 'YYYY-MM-DD HH:MM:SS'，固定30分钟采样点
    temperature  REAL NOT NULL,
    humidity     REAL NOT NULL,
    light        REAL NOT NULL,
    source_type  TEXT NOT NULL DEFAULT 'SIMULATED',
    sim_scenario TEXT NOT NULL DEFAULT 'normal'  -- 模拟器元数据，不是标签
);
CREATE TABLE disturbance_events (                 -- 扰动清单
    id TEXT PRIMARY KEY, type TEXT, start_ts TEXT, end_ts TEXT, description TEXT
);
```

## 7 天模拟器规则（simulator.py）

- 采样：固定 30 分钟一个点，2026-10-07 00:00 ~ 2026-10-13 23:30，共 336 点
- 昼夜基线：光照 6:00–18:00 正弦（正午峰值 55000 lux，夜间 5 lux）；温度日较差 16℃（15:00 峰值 30℃，3:00 谷值 14℃）；湿度与温度反相（45%–75%）
- 扰动：5 个片段分散在 6 天，各带前后 1 小时线性过渡（ramp）：
  | ID | 类型 | 时间 | 效果 |
  | --- | --- | --- | --- |
  | D1 | heat_wave | 10-08 12:00–18:00 | 温度 +8℃，湿度 -15%，光照 +10% |
  | D2 | overcast_rain | 10-09 06:00–18:00 | 光照 ×0.15，湿度 +12%，温度 -2℃ |
  | D3 | cold_front | 10-10 18:00 – 10-11 06:00 | 温度 -6℃，湿度 +10% |
  | D4 | night_light_anomaly | 10-11 21:00–23:30 | 光照恒定 8000 lux |
  | D5 | dry_dust | 10-12 00:00 – 10-13 00:00 | 湿度 -18%，温度 +3℃，光照 ×0.8 |
- 噪声：温度 σ=0.25℃，湿度 σ=1.2%，光照相对 3%；seed=42 可复现
- sim_scenario 取值：`normal` / `D1..D5` / `D1..D5:ramp_in|ramp_out`（元数据）

## API（挂载于 /B02）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /B02 | 页面（Chart.js 时序曲线） |
| GET | /B02/api/meta | 数据集元信息（采样间隔、总量、起止、DB 路径） |
| GET | /B02/api/series?start=&end= | 时间窗口内原始序列（升序） |
| GET | /B02/api/stats?start=&end= | count / min / max / avg / 趋势（首末 12 点均值对比） |
| GET | /B02/api/disturbances | 扰动清单 |
| POST | /B02/api/append | body: {"hours": 4}，从库末尾继续追加新样本 |

时间参数格式：`YYYY-MM-DD [HH:MM[:SS]]`。前端切换时间窗口时，统计与曲线同步刷新。

## 验收对照（已实测）

| 验收点 | 实测结果 |
| --- | --- |
| 数据真正写入 SQLite | 336 条 commit 落盘于 B02/data/greenmate_b02.db |
| 完全关闭后端再重启，记录仍可查询 | 已实测：停止 uvicorn（端口 HTTP 000）→ 重启 → 344 条全部可查，前后快照完全一致 |
| 新样本可继续追加 | POST /api/append 追加 8 条（336→344），时间线无缝延续 |
| 质量检查 | 11 项全 PASS（空值 0、重复 0、越界 0、断点 0、扰动 5 个覆盖 6 天） |
| 时间窗口查询 | 全窗口 336 条 / 24h 窗口 49 条，统计与曲线随窗口同步变化 |

## 调试说明

- 端口占用：B01/B02 共用 8000，`python B02/main.py` 前先停掉旧的 `python main.py` 进程
- 数据缺失：页面报「时间窗口内无数据」→ 先跑 `python B02/generate.py`
- 重建数据：`python B02/generate.py --fresh`
- 查看数据库：`sqlite3 B02/data/greenmate_b02.db "SELECT * FROM environment_samples LIMIT 5"`（或任意 SQLite 工具）
- 复现验证：`python B02/test_persistence.py --phase1` → 重启程序 → `--phase2`

## 后续 B06 复用说明

数据集固定 30 分钟间隔、7 天 336+ 点、Schema 稳定，B06 可直接复用做**时间窗口切分**：
- 按时间窗口切分样本（如 24h/48h 滑窗、固定块切分）；
- 训练/验证按时间顺序划分（勿随机打乱，避免时间泄漏）；
- 扰动清单（docs/disturbances.json）可用于标注窗口是否含扰动，但 **sim_scenario 只是模拟器元数据，不可直接当标签**；
- 追加数据保持同样的 30 分钟网格与字段结构，可无缝扩展数据集。
