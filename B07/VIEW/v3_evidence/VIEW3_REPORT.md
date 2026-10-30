================================================================
GreenMate VIEW3 · 证据空间视图
================================================================
run_id: i3-20261031013638-f78ead | 创建于 2026-10-31 01:36:38 | mode: run_agree

本视图为只读渲染：未重跑实验、未调用 LLM、未重算模型、未请求接口。分歧方向引用 S4 存档自带 synthesis 分类；缺失原因引用 S5 存档自带 missing_evidence。

## 证据空间总览（本 run_id 的判断依据）
判定：attention_confirmed（证据方向一致：历史升温（已发生）+ 模型 WATCH（推断）+ 天气升温（外部条件）均指向风险，结论可以相对明确）

### 历史证据
来源：greenmate_b02_db
内容：窗口 2026-10-08 11:30:00 ~ 2026-10-08 14:30:00，温度 26.3→38.1℃，持续升温（26.3 → 38.1℃）
有效性：有效（ok）

### 天气证据
来源：open_meteo
内容：未来 6 小时预报，温度 30.5, 31.0, 31.5℃（provider=open_meteo，forecast_time 首点=2026-10-31T02:00）
有效性：有效（ok）

### 知识证据
来源：greenmate_b04_kb
内容：检索「持续高温 未来 恶化 趋势」命中 ['K09', 'K01', 'K04']，citation=3 条（K09→knowledge/greenmate_care_guide.md#趋势判断限制; K01→knowledge/greenmate_care_guide.md#温度管理）
有效性：有效（ok）

### 模型证据
来源：greenmate_b06_rf
内容：predicted_attention=WATCH，概率={'NORMAL': 0.045, 'WATCH': 0.955}（b06-rf-v1）
有效性：有效（ok）

### 工具与运行状态
链状态：complete
- B02 历史查询（b02_db.query_series） | 调用=True | 成功=True | 转为证据=True | 采用=True | 固定窗口 2026-10-08 11:30:00~2026-10-08 14:30:00，持续升温
- B06 模型推理（load_model+predict_proba，未重训） | 调用=True | 成功=True | 转为证据=True | 采用=True | predicted_attention=WATCH（模型输出原样保留，不修改）
- B05 search_tomato_knowledge（B04 本地知识检索） | 调用=True | 成功=True | 转为证据=True | 采用=True | 命中 ['K09', 'K01', 'K04']，采用
- B05 get_weather_forecast → B03（升温桩） | 调用=True | 成功=True | 转为证据=True | 采用=True | 场景：天气升温（与内部证据一致）

## 证据分歧案例（S4 存档，方向分类引用存档 synthesis）
- 来源存档 run_id：s4-20261022202715-3741cc（verdict=attention_uncertain）
- 支持提高关注：E1, E2
- 意见相反（提示缓解）：E3
- 仅支持部分判断（不确定性）：E4
- 说明：内部证据支持提高关注，但外部天气提示可能缓解、专业知识提示趋势不能证明未来一定恶化——存在分歧，不强行合并为单一确定结论

## 证据缺失案例（S5 存档，天气 unavailable）
- 来源存档 run_id：s5-20261028153511-cd8ae2（fault=weather_unavailable，verdict=attention_weather_missing）
- 有效证据：E1, E2, E4
- 缺失证据：E3（external_weather，status=error）不可用原因：网络异常：无法连接外部天气 API，请检查网络
- 对判断的影响：天气证据缺失：无法评估未来降温等缓解/反向变化，风险判断失去天气维度
- 区分说明：「没有数据」= 证据标记 unavailable 并如实展示原因与影响，而不是从页面消失（缺失本身被当作信息呈现）。

## 一句话回答
GreenMate 的判断依据全部可追溯：历史（已发生）与模型（推断）支持提高关注；天气证据在分歧案例中提示缓解、在缺失案例中如实标注不可用；知识证据只支持部分判断。证据支持、相反、缺失三种状态在空间视图上一目了然。
