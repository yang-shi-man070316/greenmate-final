# GreenMate B06 测试记录

## 测试环境

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-10-19 |
| OS | Windows 11 Home China (10.0.22000) |
| Python | 3.8.10 |
| scikit-learn | 1.3.2（Python 3.8 兼容版本线；清华镜像安装） |
| 数据 | B02 SQLite 7 天 336 条（30 分钟网格），输入窗口 6 点（3h），预测窗口 4 点（2h） |
| 模型 | RandomForestClassifier(n_estimators=200, max_depth=8, class_weight=balanced, random_state=42) |

## 1. 窗口化单测（10/10 通过）

- 7 天 336 条样本加载、升序校验 ✅
- 默认窗口 327 个（336-6-4+1）；首窗口 10-07 00:00~02:30 → 预测 03:00~04:30 ✅
- 末窗口预测终点 = 10-13 23:30 ✅
- 窗口可回溯 B02 时段重算一致（窗口 #123：10-09 13:30~16:00）✅
- window_size=12 → 321 窗口；prediction_horizon=2 → 329 窗口；非法 horizon 拒绝 ✅

## 2. 特征/标签单测（10/10 通过）

- 8 骨架特征白名单 ✅
- 特征值手工验证（current/mean/delta 计算正确：12.5 / 52.5 / 5.17 / delta 5.0）✅
- 特征键恰好 8 个；sim_scenario / label_source / timestamp / weather 未混入 ✅
- 标签规则：基线（29~30℃/48~50%）→ NORMAL；热浪（36~38℃/30~35%）→ WATCH（hum_low+temp_high）；夜间 8000 lux → WATCH（light_night）✅

## 3. 时间切分单测（8/8 通过）

- 231 训练 + 93 测试 + 3 跨边界丢弃 = 327 ✅
- 训练集 predict_end 全部 < 10-12 00:00；测试集 predict_start 全部 ≥ 边界 ✅
- 训练最晚 10-11 23:30 < 测试最早 10-12 00:00（无时间泄露）✅
- 训练/测试均含 NORMAL 与 WATCH ✅

## 4. 训练 + 评估（实测）

```
窗口总数 327 | 训练 231 | 测试 93 | 跨边界丢弃 3
标签分布：训练 {NORMAL:194, WATCH:37} | 测试 {NORMAL:68, WATCH:25}
基线（多数类 NORMAL）：F1_weighted=0.6176，混淆矩阵 TN=68/FP=0/FN=25/TP=0（recall_WATCH=0）
ML RandomForest：F1_macro=0.7540，F1_weighted=0.8164，recall_NORMAL=0.9412，recall_WATCH=0.5200
ML 混淆矩阵：TN=64 / FP=4 / FN=12 / TP=13
特征重要性：temp_current .208 > hum_current .185 > hum_mean .126 > temp_mean .118 > temp_delta .110 > hum_delta .101 > light_mean .086 > light_current .065
```

**性能变化解释**：基线只输出多数类，完全无法发现风险（recall_WATCH=0）；ML 学到「高温/低湿/夜间强光 → WATCH」关联，WATCH 召回 0→0.52，加权 F1 提升约 0.20。特征重要性显示温度/湿度水平与变化量是主要判据，符合标签规则语义（可解释）。

**错误样本解释（FP/FN 各 1，实测）**：

- FP（假阳性，10-12 21:30~00:00 窗口）：沙尘扰动结束的快速恢复期，窗口内温度剧变 -7.6℃、湿度剧变 +25.7%，模型识别为冷锋类风险信号；但预测窗口（00:30~02:00）已回归正常 → 假警报
- FN（假阴性，10-12 05:30~08:00 窗口）：预测窗口（08:30~10:00）湿度跌破 40% 触发 hum_low；但输入窗口结束时湿度仍 47.9%（呈下降趋势），恶化发生在未来 → 过去 3 小时特征不足以提前预警（时间外推固有难点）

## 5. 保存/重载（实测通过）

- 模型 + 元数据保存至 B06/models/b06_model.joblib（version=b06-rf-v1, trained_at=2026-10-19 00:15:26）
- 重载校验：窗口定义（6/4）与 8 特征列表一致 ✅
- 端到端流水线 12/12：训练→评估→保存→重载→最新推理全链 ✅

## 6. 最新窗口推理（实测）

```
[MODEL_OUTPUT] predicted_attention=NORMAL | model_version=b06-rf-v1
概率 {NORMAL: 0.9996, WATCH: 0.0004}
输入窗口 2026-10-14 01:00:00 ~ 03:30:00（6 点，B02 追加的新样本）
特征：temp 14.3℃/hum 73.5%/light 4.0lux（夜间正常态）
不确定性：置信度 100.0%；适用边界：仅 SIMULATED 分布，与 B03/B04 证据分离
```

## 7. 端到端 API 验证

- 六模块共存：/、/B02–/B06 全部 HTTP 200
- GET /B06/api/overview：327 窗口 / 231+93+3 / 标签分布 NORMAL:263 WATCH:64
- GET /B06/api/model：模型元数据齐全
- POST /B06/api/predict：MODEL_OUTPUT + NORMAL + model_version ✅

## 8. 复现说明

1. `pip install -r B06/requirements.txt`（国内网络建议清华镜像）
2. `python B06/tests/test_*.py`（4 个单测，全部无需 LLM Key / 无需联网）
3. `python B06/train.py` → `python B06/predict.py`
4. `python B06/run.py` → http://127.0.0.1:8000/B06 页面按钮复现
