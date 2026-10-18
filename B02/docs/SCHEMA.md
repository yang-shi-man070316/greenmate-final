# GreenMate B02 数据资产说明（Schema / 规则 / 扰动清单 / 统计）

> 本文件是 B02 产出的可复用数据资产说明，后续 B06 可基于该数据集做时间窗口切分。

## 1. 数据库位置与 Schema

- 文件：`B02/data/greenmate_b02.db`（SQLite，与进程无关，重启不丢）
- 采样间隔：**30 分钟**（固定网格）
- 时间轴：2026-10-07 00:00:00 ~ 2026-10-13 23:30:00（7 天，336 点；演示追加后 344 点）
- source_type：全部为 `SIMULATED`

```sql
CREATE TABLE environment_samples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL UNIQUE,           -- 'YYYY-MM-DD HH:MM:SS'
    temperature  REAL NOT NULL,                  -- ℃，合法范围 [0, 50]
    humidity     REAL NOT NULL,                  -- %，合法范围 [0, 100]
    light        REAL NOT NULL,                  -- lux，合法范围 [0, 120000]
    source_type  TEXT NOT NULL DEFAULT 'SIMULATED',
    sim_scenario TEXT NOT NULL DEFAULT 'normal'  -- 模拟器元数据，不是标签
);
CREATE INDEX idx_samples_timestamp ON environment_samples(timestamp);

CREATE TABLE disturbance_events (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    start_ts    TEXT NOT NULL,
    end_ts      TEXT NOT NULL,
    description TEXT NOT NULL
);
```

## 2. 7 天模拟器规则（可复现）

- 随机种子：42（`--seed` 可改，生成结果确定）
- 昼夜基线（当日小时数驱动）：
  - 光照：6:00–18:00 正弦，正午峰值 55000 lux；夜间 5 lux
  - 温度：`22 + 8·sin(2π(h−9)/24)`，15:00 峰值 30℃，3:00 谷值 14℃
  - 湿度：与温度反相，45%–75%
- 扰动叠加：5 个片段（见下），前后各 2 个采样点（1 小时）线性过渡（ramp）
- 噪声：温度 σ=0.25℃（加性）；湿度 σ=1.2%（加性）；光照 3%（乘性）+ 0.5 lux（加性）
- 输出精度：温度/湿度 1 位小数，光照取整；越界值 clamp 到合法范围

## 3. 扰动清单（sim_scenario 元数据，不是标签）

| ID | 类型 | 开始 | 结束 | 效果 |
| --- | --- | --- | --- | --- |
| D1 | heat_wave | 2026-10-08 12:00 | 2026-10-08 18:00 | 温度 +8℃，湿度 -15%，光照 +10% |
| D2 | overcast_rain | 2026-10-09 06:00 | 2026-10-09 18:00 | 光照 ×0.15，湿度 +12%，温度 -2℃ |
| D3 | cold_front | 2026-10-10 18:00 | 2026-10-11 06:00 | 温度 -6℃，湿度 +10% |
| D4 | night_light_anomaly | 2026-10-11 21:00 | 2026-10-11 23:30 | 光照恒定 8000 lux |
| D5 | dry_dust | 2026-10-12 00:00 | 2026-10-13 00:00 | 湿度 -18%，温度 +3℃，光照 ×0.8 |

机器可读清单：`B02/docs/disturbances.json`

sim_scenario 取值分布（336 条基准数据）：

| 取值 | 样本数 |
| --- | --- |
| normal | 228（67.9%） |
| D1 核心区 + ramp | 8 + 3 |
| D2 核心区 + ramp | 20 + 3 |
| D3 核心区 + ramp | 20 + 3 |
| D4 核心区 + ramp | 1 + 3 |
| D5 核心区 + ramp | 44 + 3 |

## 4. 样本统计（实测，基准 336 条）

| 字段 | min | max | avg |
| --- | --- | --- | --- |
| temperature（℃） | 7.6 | 38.2 | 22.1 |
| humidity（%） | 25.5 | 86.7 | 58.4 |
| light（lux） | 0.0 | 61673.0 | 15114.3 |

趋势（首 12 点均值 → 末 12 点均值）：温度 14.8 → 22.5（上升，冷锋后回暖）；湿度 73.0 → 58.6（下降）；光照平稳。

## 5. 调试说明

- 生成/重建：`python B02/generate.py [--fresh] [--append N] [--seed 42]`
- 质量检查：`python B02/quality_check.py`（报告自动写入 docs/quality_report.md）
- 持久化验证：`python B02/test_persistence.py --phase1` → 完全关闭程序重启 → `--phase2`
- 手工查询示例：
  ```sql
  SELECT COUNT(*) FROM environment_samples;                      -- 344
  SELECT MIN(timestamp), MAX(timestamp) FROM environment_samples; -- 起止时间
  SELECT sim_scenario, COUNT(*) FROM environment_samples GROUP BY sim_scenario;
  ```

## 6. B06 复用指引（时间窗口切分）

1. 数据集特征：固定 30 分钟网格、连续时间轴、三字段数值、含扰动片段与过渡、Schema 稳定。
2. 时间窗口切分：可直接按时间窗口取样（如 24h/48h 滑窗、固定块），窗口边界落在采样网格上。
3. 划分建议：按时间顺序划分训练/验证/测试，避免随机打乱造成时间泄漏。
4. 标签边界：sim_scenario 仅描述"该点由模拟器哪种场景生成"，属于元数据；若 B06 需要标签，应基于数值与时间另行定义（如窗口内是否含扰动），不得直接复用 sim_scenario 作为 label。
5. 数据扩展：追加新样本保持同一 30 分钟网格与字段结构（generate.py --append / API /api/append），时间轴无缝延续。
