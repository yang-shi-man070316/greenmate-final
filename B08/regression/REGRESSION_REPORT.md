# GreenMate B08 第四遍 · 首轮回归报告（REGRESSION_REPORT）

- app_version：B08_baseline_01
- model_version：b06-rf-v1
- 测试时间：2026-10-31 13:43:36
- 回归案例数量：10
- 通过数量：10
- 失败数量：0
- 本轮全部 run_id：`v8-20261031134340-f5ed8e`, `v8-20261031134344-835275`, `v8-20261031134347-fdf19f`, `v8-20261031134350-1601ce`, `v8-20261031134354-11a789`, `v8-20261031134357-2694f4`, `v8-20261031134400-69fa1e`, `v8-20261031134403-e94c9d`, `v8-20261031134407-40be6c`, `v8-20261031134411-f10c3d`

## 每个案例小结

| case_id | 分组 | 是否通过 | 预期 vs 实际 | 关键差异点 |
| --- | --- | --- | --- | --- |
| case_conflict_01 | conflict | ✅ 通过 | verdict 预期['attention_uncertain']/实际attention_uncertain；模型预期['WATCH']/实际WATCH；天气预期ok/实际ok | 无 |
| case_conflict_02 | conflict | ✅ 通过 | verdict 预期['attention_uncertain']/实际attention_uncertain；模型预期['WATCH']/实际WATCH；天气预期ok/实际ok | 无 |
| case_degraded_01 | degraded | ✅ 通过 | verdict 预期['attention_weather_missing']/实际attention_weather_missing；模型预期['WATCH']/实际WATCH；天气预期unavailable/实际unavailable | 无 |
| case_degraded_02 | degraded | ✅ 通过 | verdict 预期['attention_weather_missing']/实际attention_weather_missing；模型预期['WATCH']/实际WATCH；天气预期unavailable/实际unavailable | 无 |
| case_drift_01 | drift | ✅ 通过 | verdict 预期['attention']/实际attention；模型预期['NORMAL', 'WATCH']/实际NORMAL；天气预期None/实际None | 无 |
| case_drift_02 | drift | ✅ 通过 | verdict 预期['attention']/实际attention；模型预期['NORMAL', 'WATCH']/实际NORMAL；天气预期None/实际None | 无 |
| case_stable_01 | stable | ✅ 通过 | verdict 预期['stable']/实际stable；模型预期['NORMAL', 'WATCH']/实际NORMAL；天气预期None/实际None | 无 |
| case_stable_02 | stable | ✅ 通过 | verdict 预期['stable']/实际stable；模型预期['NORMAL', 'WATCH']/实际NORMAL；天气预期None/实际None | 无 |
| case_weather_01 | weather | ✅ 通过 | verdict 预期['weather_attention']/实际weather_attention；模型预期['NORMAL', 'WATCH']/实际NORMAL；天气预期ok/实际ok | 无 |
| case_weather_02 | weather | ✅ 通过 | verdict 预期['weather_attention']/实际weather_attention；模型预期['NORMAL', 'WATCH']/实际NORMAL；天气预期ok/实际ok | 无 |

## 五条硬性校验规则覆盖

| 规则 | 覆盖案例 | 结果 |
| --- | --- | --- |
| 稳定场景不能无依据报警 | case_stable_01, case_stable_02 | ✅ |
| 漂移场景应识别变化 | case_drift_01, case_drift_02 | ✅ |
| 外部天气应影响未来判断 | case_weather_01, case_weather_02 | ✅ |
| 证据分歧应保留差异 | case_conflict_01, case_conflict_02 | ✅ |
| 证据缺失应触发限制说明 | case_degraded_01, case_degraded_02 | ✅ |

## 总结论

✅ 首轮回归全部通过：10/10 案例通过，五个分组规则全覆盖。后续修改提示词/工具/证据结构/模型加载/页面逻辑/错误处理后，运行 python B08/regression/regress.py 全量重跑即可。
