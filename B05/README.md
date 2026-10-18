# GreenMate B05 · 工具智能体（Tool Agent）

搭建**真实工具调用闭环**：LLM 自主选择工具（function calling，顺序不写死）→ 后端**真实执行** Python 函数（禁止模拟调用）→ tool_result 回填 → LLM 判断继续调用或输出最终回答。前端可视化整条链路（tool_call / execute 执行日志 / tool_result / 最终回答 / 调用序列 / 失败测试区）。

- 边界：全部代码在 B05/，**未修改 B01–B04 任何文件**；4 个工具全部复用已有模块能力
- 访问地址：http://127.0.0.1:8000/B05（B01–B05 同端口共存）
- 前置：.env 配置 LLM_API_KEY（与 B01 相同，无需重复设置）

## 快速开始（项目根目录）

```bash
python B05/run.py        # 一个进程同时提供 B01–B05
# 浏览器打开 http://127.0.0.1:8000/B05
```

## 4 个标准工具（tools.py，统一返回结构）

统一返回模板：`{status, source, provider, retrieved_at, data?, error?}`，status 仅 **ok / unavailable / error**：

| 工具 | 能力来源 | 参数 | 失败语义 |
| --- | --- | --- | --- |
| get_current_environment() | B01 内存状态（SIMULATED） | 无 | — |
| get_environment_history(hours) | B02 SQLite 历史 | hours ≥ 0（负数 → error） | 库空/窗口无数据 → unavailable |
| get_weather_evidence(location) | B03 真实天气 API | location 城市名/坐标 | 无效地点 → error（not_found） |
| search_tomato_knowledge(query) | B04 本地知识库 | query 关键词 | 无匹配 → unavailable（no_match） |

- **ok**：成功执行且有数据；**unavailable**：功能正常但无可用数据（证据缺失）；**error**：执行失败（参数非法/外部 API 错误）
- 每个工具都可**脱离 LLM 独立运行**：`python B05/tests/test_tools.py`（7 用例，含统一结构校验）

## Agent 闭环（agent.py）

```
用户任务
  → LLM（tools 定义 + system 规则，tool_choice=auto）输出 tool_call
  → 后端真实执行对应函数（记录真实耗时，execution.real=true）
  → tool_result 回填 messages（role=tool）
  → LLM 判断：继续调用工具 / 输出最终回答（最多 5 轮，防死循环）
```

- **禁止写死调用顺序**：每轮都把全部工具定义交给 LLM，由它自主决定调用哪些工具、什么顺序
- **禁止模拟调用**：tool_result 全部来自真实函数执行；参数解析失败、执行异常、未知工具都会如实记录 error 并回填
- system 规则强制：status=unavailable/error 时必须明确说明「证据缺失/不可用」，不得编造、不得假装调用成功

## 页面可视化（/B05）

- 顶部：当前环境状态（只读）+ 4 个工具清单
- 任务输入 + 预置按钮（TestA / TestB / No-source × 3，即失败测试区）
- 调用链路时间线：每轮每步展示 `tool_call`（工具+参数）→ `execute`（真实执行 ✓ + 耗时）→ `tool_result`（status 徽章 + source/provider/retrieved_at + data/error JSON）
- 最终回答 + Agent 元信息（轮数/调用次数/model）

## API（挂载于 /B05）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /B05 | 页面 |
| GET | /B05/api/tools | 4 个工具清单（name/description/parameters） |
| GET | /B05/api/current_state | 当前环境状态（只读） |
| POST | /B05/api/agent | body: {task}，完整 Agent 闭环，返回 {status, answer, steps, iterations, model} |

## 3 组验收测试（已实测通过）

```bash
python B05/tests/test_tools.py          # 工具单测：无需密钥，7 用例
python B05/tests/test_a_single_tool.py  # TestA 单工具：需密钥
python B05/tests/test_b_multi_tool.py   # TestB 多工具：需密钥
python B05/tests/test_c_no_source.py    # No-source 失败边界：需密钥
```

| 测试 | 任务 | 验收点 |
| --- | --- | --- |
| TestA 单工具 | 帮我查看当前环境状态 | 自主调用 get_current_environment、真实执行、回答引用 24.0/65.0/12000.0 |
| TestB 多工具 | 查 24h 历史 + 南京天气 + 高温低湿养护建议 | 一轮自主调用 3 个工具，回答基于多来源证据（实测：LLM 还主动指出模拟数据与真实天气的时间窗口不一致、并披露知识证据缺口） |
| No-source 失败边界 | 负数 hours / 不存在地名 / 知识库无匹配 | 工具如实返回 error/unavailable，回答明确说明证据缺失、不编造（实测 3/3） |

## 复现说明

他人复现：`python B05/run.py` → /B05 页面点预置任务按钮，或跑 4 个测试脚本。
工具单测无需密钥即可复现；TestA/B/No-source 需在 .env 配置 LLM_API_KEY。
实测记录见 B05/docs/TEST_RECORDS.md。
