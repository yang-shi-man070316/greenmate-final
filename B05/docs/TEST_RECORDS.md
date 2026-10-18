# GreenMate B05 测试记录

## 测试环境

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-10-18 |
| OS | Windows 11 Home China (10.0.22000) |
| Python | 3.8.10 |
| LLM | deepseek-chat（.env 配置，function calling 模式，temperature=0） |
| 数据依赖 | B01 内存状态 / B02 SQLite（344 条）/ B03 真实天气 API / B04 本地知识库 |

## 1. 工具单独调试（步骤2，7/7 实测通过，无需密钥）

命令：`python B05/tests/test_tools.py`

| 用例 | 结果 |
| --- | --- |
| get_current_environment() → ok，StateA 24.0℃/65%/12000lux SIMULATED | PASS ✅ |
| get_environment_history(24) → ok，49 条样本，温度 14.2~30.1℃ | PASS ✅ |
| get_environment_history(-5) → error，validation_error「hours 不能为负数」 | PASS ✅ |
| get_weather_evidence(北京) → ok，真实联网，11.0℃ 晴（open_meteo） | PASS ✅ |
| get_weather_evidence(火星城市xyz) → error，not_found | PASS ✅ |
| search_tomato_knowledge(高温 干燥 养护) → ok，K01/K02/K04 带 source 引用 | PASS ✅ |
| search_tomato_knowledge(火星土壤pH) → unavailable，no_match | PASS ✅ |

统一返回结构校验：status/source/provider/retrieved_at 齐全，status ∈ {ok, unavailable, error}，data 与 error 二选一 ✅

## 2. TestA 单工具（实测通过）

任务「帮我查看当前环境状态」：
- Round 1: `tool_call get_current_environment({})` → 真实执行 → `tool_result status=ok`
- 最终回答引用 24.0℃ / 65.0% / 12000.0 lux，并主动注明「SIMULATED 模拟数据，非真实传感器实测」
- 5 项检查全 PASS ✅

## 3. TestB 多工具（实测通过）

任务「查 24h 环境历史、南京天气、高温低湿养护建议」：
- **一轮内自主调用 3 个工具**（顺序由 LLM 决定）：get_environment_history(24)、get_weather_evidence(南京)、search_tomato_knowledge(高温低湿环境养护建议)
- 回答为结构化报告：历史统计（49 点、温度 14.2~30.1℃、趋势）｜南京真实天气（17.4℃ 小毛毛雨）｜养护建议（引用 K01/K04）
- LLM 额外表现出三个亮点：
  1. 主动指出「环境历史（10-13/10-14）与天气证据（10-18）时间不一致，不能直接对照」
  2. 主动区分「SIMULATED 模拟数据 vs 真实外部天气，来源不同勿混用」
  3. 主动披露证据缺口：「知识库未检索到低湿量化阈值条目，加湿建议仅依据 K04 定性表述」
- 6 项检查全 PASS ✅

## 4. No-source 失败边界（实测通过，3/3）

| 用例 | 工具返回 | Agent 回答 |
| --- | --- | --- |
| 查询最近 -5 小时历史 | error（validation_error） | 「查询失败：hours 不能为负数…没有获取到任何历史数据」+ 引导正确参数，未编造 |
| 查不存在的地方「火星城市xyz」天气 | error（not_found, HTTP 404） | 「该地点不存在…我不会编造该地点的天气信息」+ 引导真实地名 |
| 检索知识库「火星土壤的 pH 值」 | unavailable（no_match） | 「该证据缺失，不可用…不会凭空编造」+ 引导可检索的替代主题 |

每用例 3 项检查全 PASS ✅

## 5. 端到端验证

- 五模块共存：/、/B02、/B03、/B04、/B05 全部 HTTP 200
- GET /B05/api/tools → 4 工具清单；GET /B05/api/current_state → 与 Agent 工具同源
- POST /B05/api/agent → 完整闭环，steps 含 tool_call/execution/tool_result 全链路日志

## 6. 复现说明

1. `python B05/run.py` → http://127.0.0.1:8000/B05
2. 工具单测（无需密钥）：`python B05/tests/test_tools.py`
3. 验收三件套（需 .env 密钥）：test_a_single_tool.py / test_b_multi_tool.py / test_c_no_source.py
4. 页面预置按钮即三组用例，点按即可复现；调用链路逐轮可视化
