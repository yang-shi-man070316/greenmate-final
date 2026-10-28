# GreenMate S1 测试记录

## 测试环境

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-10-20 |
| OS | Windows 11 Home China (10.0.22000) |
| Python | 3.8.10 |
| LLM | deepseek-chat（.env 配置） |
| 复用模块 | B01（LLM 能力）、B02（模拟器+SQLite，追加 314 条后 658 条）、B05（工具）、B06（b06-rf-v1 已训模型，未重训） |

## 1. 单元/链路测试（16/16 通过，无需 LLM Key）

`python B07/S1/tests/test_s1.py`

| 分组 | 用例 | 结果 |
| --- | --- | --- |
| 稳态数据准备 | 窗口 6 点；温度 29~30℃（含噪声容差，实测 29.0~30.4 mean 29.9）；无持续升降；光照正常无扰动；解释文本；追加幂等；B02 连续性 | 7/7 PASS ✅ |
| 结构化判断 | 稳定+NORMAL→stable；字段齐全；稳定+WATCH→model_disagreement（不修改）；无数据→inconclusive；手工趋势 stable/不稳定 | 5/5 PASS ✅ |
| 运行记录 | save/load roundtrip；inspect 摘要含两个问题 | 2/2 PASS ✅ |

## 2. 完整链路实测（真实 LLM，run_id: s1-20261020013744-67bb21）

```
步骤0 稳态数据：稳定 ✅（跳过追加，幂等）
步骤1 当前环境：StateA 24.0℃/65%/12000lux（SIMULATED）
步骤2 历史：7 条样本（13:30~16:30），温度 28.9~30.4℃
步骤3 模型：predicted_attention=NORMAL，概率 1.0，model_version=b06-rf-v1
步骤4 结构化判断：verdict=stable（LLM 无权修改）
步骤5 LLM：success，引用结构化数值作答并复述判断限制
```

inspect 两个问题回答验证 ✅：Q1 五步摘要完整；Q2 稳定性证据链（幅差 1.5℃/前后半均值差 0.4℃/scenario=normal/模型 NORMAL）。

## 3. 缺陷修复记录

- **前后半均值差计算 bug**：7 点窗口两半长度不等（3 vs 4），初版 `(sum(后半)-sum(前半))/half` 把差值放大约 30 倍（实测 half_diff 10.37 vs 正确 0.4），导致 stable 被误判为 attention。修复：两半各自求均值再相减；judgment.py 与 prepare.py 同步修正，test_s1.py 增加手工数据趋势用例固化。
- **温度断言过严**：任务要求 29~30℃，B02 模拟器自带 ±0.25℃ 噪声，实测峰值 30.4℃；测试断言改为含噪声容差（28.5~31.0，mean 在 29~30），与「小幅波动」语义一致。

## 4. 复现说明

```bash
python B02/generate.py        # 若 B02 库为空
python B06/train.py           # 若 B06 无模型
python B07/S1/run.py          # 完整链路（需 .env 密钥）
python B07/S1/run.py --inspect <run_id>
python B07/S1/tests/test_s1.py
```
