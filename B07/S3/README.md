# GreenMate B07/S3 · 天气叠加对照实验（命令行）

终端运行（无网页）的对照实验：**内部稳态基线完全相同**，唯一变量是未来天气预报——
验证外部天气证据真正参与推理，风险变化可归因于天气，而不是仅展示文本。

- 复用：B05 `get_weather_forecast(location)` → B03 天气请求（S3 不写任何天气请求代码）；B01 状态、B02 固定稳态段、B06 已训模型（不重训）、S1 判断引擎与 LLM 解释（固定 prompt）
- 不新增：数据源、智能体、模型
- 字段校验：forecast_time 晚于 analysis_time（retrieved_at）；证据保留 provider / retrieved_at / forecast_time / status

## 使用（项目根目录）

```bash
python B07/S3/run.py --baseline        # 仅内部数据 → 判断 + run_id
python B07/S3/run.py --with_weather    # 相同内部数据 + 未来阴雨低光照预报 → 判断 + run_id + 两轮对比
python B07/S3/run.py --compare         # 单独打印两轮对比
python B07/S3/run.py --inspect RUN_ID  # 读取本次全部记录
python B07/S3/tests/test_s3.py         # 测试（无需 LLM Key / 无需联网）
```

## 实验设计

| 维度 | --baseline | --with_weather |
| --- | --- | --- |
| 内部数据 | B01 状态 24℃/65%/12000lux + B02 稳态段（10-20 13:30~16:30，29~30℃）+ B06 预测 | **完全相同** |
| 天气预报 | 无 | 未来 3h 降水概率 85~92%、云量 88~95%（阴雨低光照，provider=open_meteo） |
| 内部判定 | stable | stable（不变） |
| 最终判定 | stable（无需重点关注） | **weather_attention（需要重点关注）** |
| 归因 | — | **external_weather** |

## 实现要点

1. **天气请求零重写**：B03/weather_client.py 新增 `fetch_forecast`（复用既有 get_config/地点解析/超时/错误映射），B05/tools.py 新增 `get_weather_forecast` 工具统一封装；S3 只 import 调用
2. **阴雨场景可控**：--with_weather 通过 B03 既有注入机制（WEATHER_BASE_URL）把请求指向本地场景桩（forecast_stub.py，线程内 HTTP），返回确定性的「阴雨低光照」逐小时预报；预报时间基于运行时刻下一个整点起算，天然晚于 analysis_time
3. **内部数据固定**：B02 稳态段用固定常量（BASELINE_START/END = 10-20 13:30~16:30），不受库尾数据（如 S2 漂移段）影响；两轮加载完全同一段数据
4. **判定与归因**（judgment.py）：内部用 S1 引擎判定 stable；天气维度透明规则——未来 3 小时降水概率≥60% 或云量≥80% → weather_risk（云量≥80% 时外部光照被显著压低）；内部 stable + 天气风险 → verdict=weather_attention，attribution=external_weather；forecast_time 校验结果记录在 forecast_time_valid
5. **天气参与推理**：LLM 的 payload 含 weather_forecast 完整证据 + 结构化判断，固定 prompt 与 S1 一致；LLM 回答必须基于天气证据给出判断依据（验收对比中可见）

## 实测结果（2026-10-22）

- baseline：internal=stable，verdict=stable，关注等级低
- with_weather：internal=stable（与 baseline 相同），verdict=weather_attention，归因 external_weather，forecast_time_valid=True
- 两轮对比输出（终端 `--compare` 或 with_weather 运行结尾自动打印）：内部数据完全一致、风险升级全部归因外部天气
- 测试 12/12 通过（无需密钥）

## 目录结构

```
B07/S3/
├── run.py             # 主入口（--baseline / --with_weather / --compare / --inspect）
├── judgment.py        # S3 组合判定（S1 引擎 + 天气维度 + 归因）
├── forecast_stub.py   # 阴雨低光照预报场景桩（仅实验条件）
├── run_records/       # s3- 前缀运行记录
├── tests/test_s3.py   # 12 项测试
└── README.md
```
