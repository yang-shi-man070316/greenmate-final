# GreenMate B07/S1 · 稳态基线（Steady-state Baseline）

复用 B01（LLM 能力）、B02（时序数据+模拟器）、B05（工具接口）、B06（已训模型）构建
**完整执行链路**：查看当前环境 → 读取最近历史 → 模型短时预测 → 结构化判断 → LLM 自然语言解释，
输出唯一 run_id，运行记录可追溯、可回答「这次 GreenMate 看到了什么、为什么说它比较稳定」。

- 边界：仅导入调用 B01/B02/B05/B06 模块，**不复制旧模块源码**；B06 模型只加载**不重新训练**
- 目录：全部代码在 B07/S1/，运行记录在 B07/S1/run_records/

## 快速开始（项目根目录）

```bash
# 执行完整链路（自动准备稳态数据段 → 五步链路 → 保存记录 → 输出 run_id）
python B07/S1/run.py

# 按 run_id 读取本次全部记录，回答两个问题
python B07/S1/run.py --inspect s1-20261020013744-67bb21

# 仅准备稳态数据段
python B07/S1/run.py --prepare

# 测试（无需 LLM Key）
python B07/S1/tests/test_s1.py
```

前置：B02 已有数据（`python B02/generate.py`）、B06 已训练模型（`python B06/train.py`）、.env 已配置 LLM_API_KEY。

## 五步链路

| 步骤 | 实现 | 实测（run_id: s1-20261020013744-67bb21） |
| --- | --- | --- |
| 0. 稳态数据准备 | [prepare.py](B07/S1/prepare.py)：用 B02 模拟器（import 调用）从库尾连续追加到 2026-10-20 16:30，最近 3 小时自然成为 29~30℃ 白昼稳态段；输出稳定性统计解释 | 温度 29.0~30.4℃（mean 29.9）、无持续升降、scenario=normal ✅ |
| 1. 当前环境 | 调用 B05 `get_current_environment()`（source_type=SIMULATED） | StateA 24℃/65%/12000lux ✅ |
| 2. 最近历史 | 调用 B05 `get_environment_history(3)`（B02 SQLite） | 7 条样本（13:30~16:30）✅ |
| 3. 模型预测 | B06 已保存模型（joblib 加载，不重训），输出 predicted_attention + model_version，**原样保留不修改** | NORMAL（概率 1.0），b06-rf-v1 ✅ |
| 4. 结构化判断 | [judgment.py](B07/S1/judgment.py) 优先生成、独立存储：当前环境状态 / 近期趋势 / predicted_attention / 证据状态 / 判断限制；LLM 无权修改 | verdict=stable ✅ |
| 5. LLM 解释 | [llm_explain.py](B07/S1/llm_explain.py) 复用 B01 LLM 能力，**固定 prompt**：「分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。」环境数据/历史/预测/判断全部传入 | success，解释引用结构化数值与限制 ✅ |

## 结构化判断规则（透明）

- 数据稳定 + 模型 NORMAL → `stable`
- 数据稳定 + 模型 WATCH → `model_disagreement`（**只标记不修改模型结果**，`model_output_modified: false`）
- 数据不稳定 → `attention`
- 证据不足 → `inconclusive`

「数据稳定」= 温度 3 小时幅差 ≤2℃ 且前后半均值差 ≤0.5℃；湿度幅差 ≤10% 且前后半均值差 ≤3%；全部样本 sim_scenario=normal。

> 实测发现并修复：7 点窗口的前后半长度不等（3 vs 4），初版直接把两半之和相减导致 half_diff 放大 30 倍
> （10.37 vs 实际 0.4），已改为两半各自求均值再相减，并有测试固化（test_s1.py 趋势用例）。

## 运行记录（run_records/）

每次执行生成唯一 `run_id`（s1-时间戳-随机后缀），记录内容：
稳定性数据统计、五步每步完整结果、chain_status（LLM 不可用时仍保存完整结构化结果）、结构化判断原文。

`--inspect RUN_ID` 回答两个问题：
- **Q1 这次 GreenMate 看到了什么？** —— 五步逐步摘要
- **Q2 最后为什么说它比较稳定？** —— 幅差/前后半均值差/无扰动/模型 NORMAL 的证据链 + LLM 解释

## 设计要点

- **LLM 无权修改结构化结果**：判断在调用 LLM 之前生成并落盘，LLM 只能基于它解释；LLM 失败不影响判断与记录
- **模型结果不修改**：B06 输出原样进入结构化判断；与数据稳定性矛盾时标 `model_disagreement`，绝不强行改成 NORMAL
- **数据诚实标注**：全部 SIMULATED；当前值（B01 内存 24℃）与历史（B02 时序 29~30℃）来源不同，判断中如实分列
- **稳态数据解释**：为什么稳定——温度幅差、无持续升降、湿度窄幅、光照正常白天区间、无扰动、SIMULATED
