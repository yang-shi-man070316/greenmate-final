# GreenMate B06 · 机器学习闭环（可解释 · 可复现 · 传统 ML）

复用 B02 环境样本构建传统机器学习闭环：**最近 6 点（3 小时）输入窗口 → 8 个骨架特征 → 预测未来 1–2 小时 next_window_attention（NORMAL / WATCH）**。

- 边界：全部代码在 B06/，**未修改 B01–B05 任何文件**；不使用深度学习/YOLO；测试集不参与训练
- 特征纪律：仅 current/mean/delta 8 个骨架特征——**原始样本序列、sim_scenario、label_source、B03 天气数据均不进入特征**（白名单强制 + 单测断言）
- 访问地址：http://127.0.0.1:8000/B06（B01–B06 同端口共存）

## 快速开始（项目根目录）

```bash
pip install -r B06/requirements.txt   # scikit-learn（Python 3.8 → 自动解析 1.3.2）
python B06/run.py                     # 一个进程提供 B01–B06
# 浏览器打开 http://127.0.0.1:8000/B06 → 点「训练 + 评估 + 保存」→「最新 6 点推理」
```

命令行等价流程：

```bash
python B06/train.py       # 训练+评估+保存+重载验证（打印完整指标与错误样本解释）
python B06/predict.py     # 最新窗口推理（predicted_attention + model_version）
```

## 六步落地

| 步骤 | 实现 | 实测 |
| --- | --- | --- |
| 1. 切时间窗口 | [windowing.py](B06/windowing.py)：按 timestamp 升序，输入 6 点（3h）/ 预测 4 点（2h，可改 2~4）；window_size 可改；每个样本记录完整时段，可回溯 B02 重算验证 | 327 窗口；回溯重算一致 ✅ |
| 2. 特征/标签 | [features.py](B06/features.py) 8 骨架特征（current×3 + mean×3 + delta×2）；[labeling.py](B06/labeling.py) 透明规则生成 WATCH（temp>31 / temp<13 / hum<40 / hum>85 / 夜间光照>500），label_source 仅元数据 | 白名单 8 列、基线不触发/扰动触发 ✅ |
| 3. 时间切分 | [dataset.py](B06/dataset.py)：前 5 天训练、后 2 天测试；预测窗口跨边界丢弃；训练/测试时间不重叠 | 231 训练 / 93 测试 / 3 丢弃，无泄露 ✅ |
| 4. 训练+评估 | [train.py](B06/train.py)：多数类基线 → RandomForest（seed 固定）→ 混淆矩阵/F1/召回 → 错误样本解释 | ML F1_weighted **0.8164** vs 基线 **0.6176**；recall_WATCH 0→0.52 ✅ |
| 5. 保存/重载 | joblib 保存模型+元数据（版本/特征列表/窗口配置/指标）；重载时校验一致 | 重载校验通过 ✅ |
| 6. 最新推理 | [predict.py](B06/predict.py)：B02 最新 6 点 → 特征 → predicted_attention + model_version，标记 **MODEL_OUTPUT**，含不确定性与适用边界；与 B03 天气/B04 知识分离 | NORMAL（置信 99.96%）✅ |

## 核心特征含义（可解释性）

- `temp_mean` / `hum_mean`：窗口 3 小时整体水平——直接刻画「这段时间偏热/偏干」
- `temp_delta` / `hum_delta`：窗口期变化方向——正值升温/增湿（热浪逼近），负值降温/变干（冷锋/干燥）
- `light_current` + `light_mean`：结合昼夜位置由标签规则解读（夜间高光照=异常，见 labeling.py）
- 光照不设 delta：光照由昼夜节律主导，窗口内 delta 无稳定语义

## 实测评估（2026-10-19，327 窗口，测试集 93）

| 模型 | F1 macro | F1 weighted | recall NORMAL | recall WATCH |
| --- | --- | --- | --- | --- |
| 多数类基线（NORMAL） | — | 0.6176 | 1.0 | **0** |
| RandomForest（b06-rf-v1） | 0.7540 | **0.8164** | 0.9412 | **0.5200** |

混淆矩阵（ML）：TN=64, FP=4, FN=12, TP=13。

**性能变化解释**：基线只会输出多数类，WATCH 召回为 0——完全无法发现风险。ML 从 8 个骨架特征中学习到「高温/低湿/夜间强光」与 WATCH 的关联，把 WATCH 召回提到 0.52、加权 F1 提升 0.20。

**错误样本解释（实测）**：
- 假阳性 FP（10-12 21:30 窗口）：沙尘扰动结束后的快速恢复期，窗口内温度剧变 -7.6℃、湿度剧变 +25.7%，模型把它当成冷锋类风险信号，但预测窗口已回归正常——假警报
- 假阴性 FN（10-12 05:30 窗口）：预测窗口内湿度跌破 40% 触发 hum_low，但输入窗口结束时湿度仍 47.9%，恶化过程发生在未来——过去 3 小时特征不足以提前预警（时间外推的固有难点）

## 测试（全部无需 LLM Key / 无需联网）

```bash
python B06/tests/test_windowing.py    # 窗口数/时段/回溯/可改参数（10 项）
python B06/tests/test_features.py     # 8 特征白名单/手工验证/禁止混入/标签规则（10 项）
python B06/tests/test_split.py        # 时间边界/无泄露/跨边界丢弃/两类齐全（8 项）
python B06/tests/test_pipeline.py     # 训练→评估→保存→重载→推理 端到端（12 项）
```

实测记录见 [docs/TEST_RECORDS.md](B06/docs/TEST_RECORDS.md)。

## 模型资产（保存/重载）

- [models/b06_model.joblib](B06/models/b06_model.joblib)：模型 + 元数据（版本 b06-rf-v1、特征列表、窗口配置、指标、错误样本）
- 重载校验：窗口定义（window_size/prediction_horizon）与特征列表必须一致，不一致拒绝加载——保证模型版本与输入窗口定义绑定
- 完全重启后可加载：`from train import load_model` 或页面直接点「最新 6 点推理」

## 适用边界（必须了解）

- 仅适用于 B02 SIMULATED 模拟数据分布（30 分钟网格、同一模拟器规则）
- 预测是**时间外推**：未来 1–2 小时内的变化若未在输入窗口中出现前兆，模型无法预知（FN 样例即此情况）
- 预测结果（MODEL_OUTPUT）独立于 B03 天气证据与 B04 知识证据，三者不可混用
- 对超出训练分布的真实环境不具备泛化保证
