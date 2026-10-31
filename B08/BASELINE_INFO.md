# GreenMate B08 基线版本说明（BASELINE_INFO）

- 冻结时间：2026-10-31 04:38:42

## 版本标记（本轮验证全程固定，禁止动态切换）

| 版本项 | 值 |
| --- | --- |
| app_version | **B08_baseline_01** |
| model_version | **b06-rf-v1**（B06 已保存模型，本轮不重训、不切换） |
| 知识资料版本 | b04_kb_v1（K01~K09，knowledge_base.json version 1.0） |
| 固定提问 | 结合全部可用证据，分析当前番茄生长环境风险：哪些方面可以判断，哪些方面因证据受限无法判断？ |

## 冻结场景清单（scenarios/，每个绑定 scenario_id，支持按 id 加载回放）

| scenario_id | 场景 | 来源模块 | 源 run_id | 判定快照 |
| --- | --- | --- | --- | --- |
| b08_s1_steady | S1 稳态基线 | B07/S1 | `s1-20261020212515-1d9ba6` | stable |
| b08_s2_drift | S2 渐进漂移 | B07/S2 | `s2-20261021221953-964d11` | attention |
| b08_s3_weather | S3 天气叠加 | B07/S3 | `s3-20261022194350-9457a8` | weather_attention |
| b08_s4_multi | S4 多源分歧 | B07/S4 | `s4-20261022202715-3741cc` | attention_uncertain |
| b08_s5_degraded | S5 证据退化（天气缺失） | B07/S5 | `s5-20261028153511-cd8ae2` | attention_weather_missing |

## 两种运行模式

- **真实链路模式**（live）：实时调用天气 API、B06 模型、LLM，验证链路与异常退化；
- **回归回放模式**（replay）：加载 scenarios/ 快照证据，输入完全固定，重复运行条件一致（不查询任何数据源、不调用 LLM/模型/天气）。

## 冻结原则

- B08 不新增功能、不修改 B07 已完成的创新机制；
- 本文件与快照由 python B08/freeze.py 生成；重新冻结前请确认 B07 基线未变化。
