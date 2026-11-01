GreenMate 番茄生长环境分析系统技术文档（GREENMATE_TECH_DOC）

文档范围：B01~B08 全部模块、B07 五套边界检查、B08 五轮验证、B08 创新模块。
所有结论均来自项目内真实代码、存档（run 记录 / 快照 / 报告），未引用项目外未经证实的内容。

1. 项目目标与边界

1.1 解决什么问题

GreenMate 是一个教学原型系统，验证的核心问题由 B01 确立（见根目录 README.md）：

「网页展示的环境状态，AI 是否真的读到了？」

由此扩展出整条演进主线：

1）状态必须进入上下文：页面展示的环境数据与送给 LLM 的环境数据必须是同一份（B01）。
2）判断必须由证据驱动：系统对环境风险的下结论，要能逐条对应到真实获取到的证据（B02~B07 逐步建立时序证据、天气证据、知识证据、模型证据）。
3）结论必须可验证：固定提问、冻结场景、可回放、可对照、可回归复测（B08）。

系统最终形态：针对番茄生长环境（温度/湿度/光照），整合内部历史、外部天气、本地知识、机器学习预测四类证据，输出环境风险提示（verdict + 自然语言解释），并保证每次判断可追溯到具体证据与版本。

1.2 不解决什么问题

- 不做植株病害诊断：系统只输出环境风险提示，不判断「这株番茄得了什么病」（边界检查1）。
- 不做设备自动控制：系统只做提示告知，不输出自动灌溉、自动通风、触发设备动作等控制指令（边界检查2）。
- 不把知识资料当诊断结论：知识库检索结果只是「专业资料的通用规律」，不是对当前植株的确诊（边界检查3）。
- 不编造没有拿到的证据：某类证据缺失时如实说明并收缩判断，不靠 LLM 常识补写（边界检查4）。
- 不做产量预测、不做施肥推荐（边界检查1 违禁项）。
- 不是真实农业落地产物：环境数据为模拟数据（SIMULATED），模型标签为规则推导（DERIVED_LABEL），全项目未接入真实传感器，结论未经真实种植验证。

1.3 为什么选择番茄生长环境作为载体

- 番茄对温度、湿度、光照都有明确的适宜区间（本地资料 B04/knowledge/greenmate_care_guide.md），环境风险可数值化、可构造梯度场景（稳态/升温/阴雨/证据缺失）。
- 番茄栽培知识资料公开且可本地化，适合做「可追溯引用」的知识证据（K01~K09）。
- 环境风险（高温胁迫、低湿等）与「植株疾病」之间存在清晰边界，适合用来演示和检验「说到哪里为止」的合规约束。

2. 系统总体结构

2.1 B01~B06 分别提供什么能力

- B01（项目根目录 main.py / states.py / llm.py / static）：环境状态唯一数据源在服务端内存（states.py，StateA/StateB 可切换，source_type=SIMULATED）；提问时服务端把同一份状态 JSON 显式拼进 LLM 上下文；页面 + LLM 问答 + 失败测试（tests/run_failure_tests.py）。
- B02（B02/）：SQLite 时序持久化（data/greenmate_b02.db）；模拟器（simulator.py）生成 30 分钟间隔、7 天 336 点网格 + D1~D5 扰动；质量检查（quality_check.py）；重启持久化验证（test_persistence.py）。
- B03（B03/）：真实天气 Web API（weather_client.py：open_meteo 主源、qweather 备源；WEATHER_BASE_URL 等环境变量注入用于桩测试）；weather_evidence 证据结构；超时/429 异常测试。
- B04（B04/）：本地知识检索（retriever.py：关键词双向子串匹配打分，top_k=3）；知识库 knowledge_base.json v1.0（K01~K09 九段）；强制引用来源、禁止伪造引用；无匹配时输出「未找到相关知识」。
- B05（B05/）：工具智能体（agent.py）：LLM 通过 function calling 自主选择并真实执行 4 个标准工具（get_current_environment / get_environment_history / get_weather_evidence / search_tomato_knowledge），工具结果带 status（ok/unavailable/error）；页面可视化展示工具调用链路。
- B06（B06/）：机器学习闭环（train.py / predict.py）：B02 最近 6 点（3 小时）→ 8 个骨架特征 → RandomForest 预测未来 1~2 小时 NORMAL/WATCH；模型保存/重载一致；输出标记 MODEL_OUTPUT；模型版本 b06-rf-v1。

2.2 B07 怎样把这些能力组织成一个系统

B07 只做一件事：复用 B01~B06 的模块能力（仅导入调用，不复制源码、不修改旧模块），把它们串成一条带存档的推理链路。

- S1 稳态基线（B07/S1）：五步链路——查看当前环境（B01/B05）→ 读取最近历史（B02）→ 模型短时预测（B06，只加载不重训）→ 结构化判断（judgment.py，规则判定，LLM 无权修改）→ LLM 自然语言解释（固定 prompt）。每次运行输出唯一 run_id，记录存 run_records/，可用 --inspect RUN_ID 回查。
- S2 渐进漂移（B07/S2）：同一瞬时读数、同一提问、同一模型，唯一变量是 B02 历史时序（漂移段由 drift_inject.py 注入）——验证趋势识别由历史证据驱动。
- S3 天气叠加（B07/S3）：--baseline / --with_weather 两轮对照，天气证据经 B05 get_weather_forecast → B03 获取，校验 forecast_time 晚于 analysis_time，验证外部证据真实参与判断。
- S4 多源分歧（B07/S4）：四类证据同时上场且方向相反（历史升温 + 模型 WATCH 指向风险；未来降温预报指向缓解；K09 知识提示「趋势不能证明未来一定恶化」），系统保留分歧、输出不确定性，不强行合并成单一结论；每条结论绑定证据编号（E1~E4）。
- S5 证据退化（B07/S5）：单一故障注入（weather_unavailable / rag_insufficient / tool_error），验证系统不崩溃、不编造、收缩判断范围并明确标注局限。
- 创新点 1~3：时序演化推理对照（S1 innovate1.py + S2 innovate1_ext.py，INNOVATE_1_REPORT.md）、多源信息证据化与反向溯源（S3 i2_evidence.py + S4 i2_trace.py，EVIDENCE_TRACE_REPORT.md）、表达强度跟随证据条件（S5 i3_run.py / i3_check.py 等，INNOVATE_3_REPORT.md）。
- VIEW1~4：四个只读静态视图（状态总览 / 状态演化 / 证据空间 / 场景回放对比），每个视图带独立 check 脚本与 REPORT。
- 边界检查 1~5：五套独立扫描脚本（boundary_check_1.py ~ boundary_check_5.py），对 S1~S5 全部存档与视图文本做越界语句扫描，报告见 BOUNDARY_CHECK1_REPORT.md ~ BOUNDARY_CHECK5_REPORT.md。

2.3 B08 怎样验证这个系统

B08 不新增功能、不修改 B07 机制，只做冻结与验证：

- 冻结（freeze.py）：把 S1~S5 五个场景固化为 scenarios/ 快照，每个绑定 scenario_id；产出 BASELINE_INFO.md；版本全程锁定（app_version=B08_baseline_01，model_version=b06-rf-v1）。
- 回放（replay.py）：只读加载快照执行固定提问，不查询任何数据源、不调用 LLM/模型/天气，重复运行输出一致。
- 验证五轮：第1轮 基线冻结 → 第2轮 S1~S5 正式验证（verify.py，五条 v8 记录，VERIFY_SUMMARY.md）→ 第3轮 三大证明（同题对照 / 真实失败注入 / 完整溯源，B08/trace/）→ 第4轮 固定回归套件（regress.py，10 案例全通过）→ 第5轮 材料固化（该轮产出已按项目方要求删除，见 7.3）。
- 创新模块（B08/innovate/）：三个独立后置分析工具（证据可信度打分 / 风险溯源可视化 / 历史轨迹差分），只读分析 B01~B08 全部历史存档，产出归档至 B08/innovate/output/。

3. 数据与场景

3.1 当前环境数据从哪里来

- 唯一数据源：B01 states.py 服务端内存，字段 temperature / humidity / light，标记 source_type=SIMULATED，StateA/StateB 可切换。
- B05 的 get_current_environment 工具读取的是同一份内存状态（与 B01 同源），保证「页面展示什么，工具就拿什么」。
- 全项目没有真实传感器；模拟数据这一事实在所有存档中以 SIMULATED 标签固化。

3.2 历史数据怎样组织

- B02 simulator.py：固定 30 分钟一个采样点，7 天 = 336 点（TOTAL_SAMPLES = 7×24×60÷30）；基线为昼夜正弦曲线，叠加 5 个扰动事件 D1~D5（heat_wave / overcast_rain / cold_front / night_light_anomaly / dry_dust）与噪声，随机种子固定（DEFAULT_SEED=42），可复现。
- 持久化到 SQLite（B02/data/greenmate_b02.db），重启后数据仍在（test_persistence.py 验证）。
- 每个采样点带 sim_scenario 字段，但该字段仅作元数据，不进 B06 模型特征、不作训练标签（B06 特征白名单强制 + 单测断言）。
- 实验注入：S2 漂移段由 drift_inject.py 向数据库注入，与模拟器网格数据同结构。

3.3 S1~S5 分别改变什么条件

- S1 稳态基线（scenario_id=b08_s1_steady）：改变的条件——无（基准）；其余条件——3 小时稳定数据 29~30℃，小幅波动。
- S2 渐进漂移（scenario_id=b08_s2_drift）：改变的条件——历史时序：同一瞬时读数（30℃ 附近），历史从「波动」换成「25.0→30.0℃ 持续升温」；其余条件——提问、模型、配置不变。
- S3 天气叠加（scenario_id=b08_s3_weather）：改变的条件——外部天气证据：叠加阴雨低光照预报；其余条件——内部证据与 S2 同属升温型。
- S4 多源分歧（scenario_id=b08_s4_multi）：改变的条件——证据方向：四类证据都存在但方向相反（升温风险 vs 降温缓解 vs 趋势限制）；其余条件——全部证据有效。
- S5 证据退化（scenario_id=b08_s5_degraded）：改变的条件——天气证据失效：status=unavailable；其余条件——其余证据正常，系统继续运行。

对照数据实录（B08/trace/CONTRAST_REPORT.md）：S1 历史前后半均值差 +0.40℃，S2 +2.92℃，最终判定 stable → attention；S3 在升温内部证据之上因天气证据升级为 weather_attention；S4 分歧保留为 attention_uncertain；S5 缺失收缩为 attention_weather_missing。

3.4 scenario_id 怎样固定和复现

- python B08/freeze.py 为五个场景生成快照 B08/scenarios/b08_xxx.json（五个），每个绑定唯一 scenario_id，并记录来源模块、源 run_id（如 b08_s2_drift 的源 run 是 s2-20261021221953-964d11）、冻结时间。
- 快照字段（见 b08_s2_drift.json）：scenario_id / name / source_module / source_run_id / app_version / model_version / knowledge_version / frozen_at / fixed_question / observation / history_series / weather_evidence / knowledge_citation / judgment_snapshot / frozen。
- 回放（python B08/run.py --replay --scenario b08_s3_weather）只读加载快照：不查 B02、不调天气 API、不跑模型、不调 LLM，输入完全固定，重复运行输出一致；附加 --check 可做快照字段完整性自检。
- 因此场景复现不依赖任何外部服务状态，也不受模拟器数据推进影响。

4. 核心机制

4.1 机制一：连续状态认知（趋势来自时序，不是来自瞬时读数）

实现逻辑（结合真实字段）：

1）历史读取：S1 链路第二步调 B05 get_environment_history → B02 SQLite 取最近 3 小时逐点序列，结果以 step2_recent_history_3h.data.samples 形式进入记录（v8 记录中为 history_window 字段，7 个点）。
2）趋势计算（B07/S1/judgment.py trend_of）：温度稳定条件 = 窗口内 max−min ≤ 2.0 且前后半均值差 |half_diff| ≤ 0.5；湿度类似（≤10.0 / ≤3.0）。half_diff 是「前后半段均值差」，用整个窗口的形态说话，而不是只看当前值。
3）模型侧同样吃窗口：B06 输入是最近 6 点（3 小时），8 个特征中有 3 个 mean 特征 + 2 个 delta 特征（temp_delta/hum_delta），本身就是「连续状态」的压缩表示。
4）结构化判断组合两者（judgment.py build_judgment）：数据平稳且模型 NORMAL → stable；数据平稳但模型 WATCH → model_disagreement（如实标记冲突，不修改模型输出，model_output_modified=False）；数据不平稳 → attention。

机制有效性由对照实验证明，不是概念宣称：创新点1 三组对照（run_current_only / with_history / with_history_prediction）与 S2 实验（EXPERIMENT_REPORT.md）都表明：同一瞬时读数下，仅更换历史时序，趋势（half_diff +0.40 vs +2.92℃）与最终判定（stable vs attention）随之变化（B08/trace/CONTRAST_REPORT.md 对照1）。

4.2 机制二：多源证据组织（工具调用 ≠ 证据采用，每条结论绑定证据）

1）统一证据字段：所有证据统一为 source_type / source / time / status / result（+ error / citation / model_version / provider / forecast_time 按需）。四类证据 source_type 分别为 internal_history、external_weather、local_knowledge、ml_prediction。
2）调用与采用分离：B05 工具被调用 ≠ 结果被采用。源存档 pipeline_log 记录每个工具的四态：调用 / 成功 / 转为证据 / 采用；S4 证据层分 adopted_evidence（采用）与 missing_evidence（缺失），TRACE_FULL.md 中 E1~E4 即为「采用」的四条证据。
3）方向分类（B07/S4/judgment.py classify_evidence）：每条证据按对风险的方向归入三类——support_attention（支持提高关注）/ mitigating_or_reverse（反向提示缓解）/ insufficient（限制、不确定性），构成 structured_judgment.synthesis。B08 创新模块的溯源视图直接复用该分类，不另造归因。
4）结论绑定证据：LLM 解释为三段式（可判断的方面 / 因证据受限无法判断的方面 / 综合提示），每条结论标注证据编号（如 [E1][E4-K01]），反向查询（S4 --inspect 含「结论依据哪些证据」）可逐条核查。

4.3 机制三：可信等级与判断边界（能说到什么程度，由证据和规则共同决定）

1）verdict 阶梯：stable / attention（S1 引擎，另有 model_disagreement、inconclusive）→ weather_attention（S3）→ attention_uncertain（S4）→ attention_weather_missing（S5）→ attention_confirmed（创新点3，证据方向一致时）。每一级对应不同的证据组合状态，不是随意措辞。
2）边界规则锁死输出边界（B07 五套边界检查，见 7.2）：环境风险 ≠ 植株疾病；预测 ≠ 控制；知识证据 ≠ 诊断事实；有什么证据说到哪里；可溯源可回放可对照。
3）证据可信度量化（B08/innovate/score/evidence_score.py）：四类证据各打 0~1 单项分，按权重时序 0.5 / 天气 0.3 / 知识 0.2 加权综合（模型单项单独展示不参与加权）；置信文案三档——≥0.8「证据充足，参考价值高」、0.4~0.8「证据存在瑕疵，结论仅供参考」、<0.4「证据质量差，建议复核数据源」。
4）关键语义区分：场景本来就没有某类证据 → 单项 null，综合权重归一化剔除（「没有」）；证据存在但失效 → 单项 0，参与加权拉低总分（「坏了」）。实测：S5 天气失效单项 0.0，综合 0.48；S1 无天气证据剔除后综合 0.90（INNOVATE_SUMMARY.md）。

5. 模型与知识

5.1 B06 模型：输入、输出、训练与版本

- 输入：B02 最近 6 个采样点（3 小时）→ 8 个骨架特征：current×3（temp/hum/light）、mean×3、delta×2（temp_delta/hum_delta）。特征白名单强制：原始样本序列、sim_scenario、label_source、B03 天气数据均不进特征。
- 输出：next_window_attention（NORMAL / WATCH）+ 各类概率 + model_version + 输入窗口时间范围；输出标记 MODEL_OUTPUT，与天气证据、知识证据明确区分（B06/predict.py）。
- 训练：标签由透明规则生成（labeling.py：temp>31 / temp<13 / hum<40 / hum>85 / 夜间光照>500 触发 WATCH，标记 DERIVED_LABEL，label_source 仅元数据）；时间切分前 5 天训练 / 后 2 天测试，预测窗口跨边界丢弃，训练测试不重叠（231 训练 / 93 测试 / 3 丢弃，train_end_boundary=2026-10-12 00:00:00）；模型为 RandomForest（n_estimators=200，max_depth=8，random_state 固定，可复现）。
- 基线对比与实测指标（models/model_metadata.json）：朴素基线（多数类 NORMAL）f1_macro=0.4224、recall_WATCH=0.0；ML 模型 f1_macro=0.754、f1_weighted=0.8164、recall_WATCH=0.52。指标仅用于说明传统 ML 优于朴素基线，不宣称农业级精度。
- 版本：model_version=b06-rf-v1，训练时间 2026-10-20 01:03:11，保存为 models/b06_model.joblib；保存后重载预测一致（B06 train.py 重载验证）。B08 全程锁定此版本，不重训、不切换（BASELINE_INFO.md）。

5.2 B04 知识来源、检索方式、引用规则

- 来源：本地资料 B04/knowledge/greenmate_care_guide.md 整理为 knowledge_base.json（version 1.0，9 段：K01~K09，如 K01 温度适宜范围、K04 高温应对、K09 高温趋势判断限制）。
- 检索方式：retriever.py 对文本归一化后做关键词双向子串匹配打分（片段包含查询关键词加分，子串部分匹配加分），取 top_k=3；返回结果带 retrieved_at / score / matched_keywords，检索过程可追溯。不使用 Embedding / 向量数据库 / 训练微调。
- 引用规则：每条知识证据必须带 source（如 knowledge/greenmate_care_guide.md 温度管理一节）与 id（K01~K09）；检索无匹配时如实输出「未找到相关知识」，禁止伪造引用；知识证据在最终解释中只能以「资料指出通用规律 + 引用来源」的形式出现，不得转化为对当前植株的诊断（边界检查3）。

5.3 模型输出与知识引用是两类不同证据

- 性质：模型输出是统计推断——基于本系统历史数据训练，对下一窗口的预测；知识引用是外部资料——公开栽培资料中的通用规律。
- 标记：模型输出标记 MODEL_OUTPUT；知识引用带 source / id / retrieved_at / score 的引用。
- 约束：模型输出受「预测 ≠ 事实、预测 ≠ 控制」约束（边界检查2）；知识引用受「知识证据 ≠ 当前对象诊断事实」约束（边界检查3）。
- 在判断中的角色：模型输出作为一类证据参与方向分类（如 S4 中 E2 支持关注）；知识引用作为一类证据参与方向分类（如 S4 中 E4 提供限制）。

两者在证据层分字段记录（model_evidence / knowledge_evidence），在 B08 创新模块打分中模型单项单独展示、不参与 0.5/0.3/0.2 加权——防止模型推断冒充观测证据。

6. 统一运行与运行追踪

6.1 run_id 如何生成

格式：前缀-YYYYMMDDHHMMSS-6位随机hex（B07/S1/records.py make_run_id，各场景同构）。

前缀体系：s1- / s2- / s3- / s4- / s5-（B07 五场景）、i1- / i1x- / i2- / i3-（三个创新点实验）、v8-（B08 验证与回归）。run_id 是存档文件名，也是所有回查入口。

6.2 一次完整运行记录哪些内容

以 B08 第二遍验证记录（B08/verify/v8-20261031072949-fee711.json）为例，一条 v8 记录包含以下顶层字段：

- scenario_id / run_id / app_version / model_version / analysis_time / location
- current_state_input（当前观测，SIMULATED）
- history_window（历史逐点序列）
- weather_evidence（天气证据，含 status / provider / forecast_time / hourly）
- knowledge_evidence（知识引用列表，含 id / source / topic）
- model_evidence（模型版本 + 锁定说明 + source_prediction 概率）
- tool_runtime_status（LLM 调用状态/模型名/耗时 + 天气链路校验 + 回放标记）
- structured_judgment（verdict + verdict_note）
- llm_explanation（LLM 固定提问下的完整回答）
- limitations（本次运行的边界说明）
- verify_result（自动核验各项与是否通过）

6.3 工具调用、证据状态、模型版本、最终判断之间的关联

关联链固化在两类位置：

1）源存档 pipeline_log（B07 实验记录）：每个工具一行——调用 / 成功 / 转为证据 / 采用 四态；据此区分「工具被调用了」与「结果被采用了」。
2）完整溯源文档（B08/trace/TRACE_FULL.md，对象 v8-20261031072949-fee711）：从固定提问出发，逐步列出当前状态输入（38.1℃/27.8%/48794 lux）→ 历史 7 点（26.3→38.1℃）→ 四个工具调用 → 四条证据 E1~E4 → 证据方向分类（E1/E2 支持、E3 反向、E4 限制）→ verdict=attention_uncertain → LLM 三段式解释。任意一条 run_id 都可以从最终结论反向追溯到输入、工具、证据、版本。

回查入口：python B07/S1/run.py --inspect RUN_ID（S1~S5 同构）、python B08/verify.py --inspect RUN_ID。

7. 验证方法与结果

7.1 S1~S5 验证结果：问题对照、失败验证、回归测试

（1）正式验证（B08/verify/VERIFY_SUMMARY.md，2026-10-31）：

- b08_s1_steady（run_id=v8-20261031072937-a6b34e）：通过——稳定条件下给出稳定判断，未凭空拔高风险；条件、判断、记录可以对应。
- b08_s2_drift（v8-20261031072941-cbce4e）：通过——瞬时读数相近、历史时序不同时趋势与关注程度发生变化，历史信息参与推理。
- b08_s3_weather（v8-20261031072945-389510）：通过——天气证据参与未来趋势判断，真实 API 链路单独校验通过，外部证据影响预测而非仅展示。
- b08_s4_multi（v8-20261031072949-fee711）：通过——证据冲突时保留差异、输出不确定性，未强行合并成单一确定结论。
- b08_s5_degraded（v8-20261031072952-75625a）：通过——某一路证据缺失时系统继续工作、缩小判断范围，未整体崩溃、未编造缺失证据。

（2）同题对照（B08/trace/CONTRAST_REPORT.md，三大证明之证明一）：固定提问不变，三组对照——S1↔S2（历史过程有效：+0.40℃ vs +2.92℃ → stable vs attention）、S2↔S3（天气真实参与：attention → weather_attention）、S4↔S5（分歧 ≠ 退化：attention_uncertain vs attention_weather_missing）。差异均可对比解释，结论均给出因果链。

（3）失败验证（B08/trace/FAILURE_REPORT.md，证明二）：主动制造天气 API 网络失败（指向未监听端口），新 run_id=v8-20261031133304-c7929f。结果：失败记录保留（status=unavailable，error_type=network_error）；LLM 明确输出限制条件（「天气维度缺失……无法评估未来是否降温」）；历史/知识/模型模块正常继续；未崩溃、未编造缺失数据。

（4）回归测试（B08/regression/REGRESSION_REPORT.md + REGRESSION_SUMMARY.md，第四遍验收）：10 个固定案例（S1~S5 衍生变体，五组各 2 例：case_stable_01/02、case_drift_01/02、case_weather_01/02、case_conflict_01/02、case_degraded_01/02），预期 verdict/模型/天气状态与实际全部一致，10/10 通过、0 失败；本轮 run_id 为 v8-20261031134340-f5ed8e ~ v8-20261031134411-f10c3d。python B08/regression/regress.py 一键全量重跑。

7.2 B07 五套边界检查结论（boundary_check_1 ~ boundary_check_5）

扫描范围（以 BOUNDARY_CHECK2_REPORT.md 为准）：S1~S5 run 存档 74 个 json + 视图 md 报告 4 个 + 视图页面 4 个；json 定位到字段路径，md/html 定位到行号。

- boundary_check_1（定位）：环境风险 ≠ 植株疾病；禁止植株疾病诊断/产量预测/施肥推荐/设备自动控制。结论：通过。提示级命中（遮阴/通风/浇水等环境管理建议）经审阅属辅助判断范围，符合边界。
- boundary_check_2（控制）：预测 ≠ 控制；禁止自动灌溉/自动通风/自动开启设备/执行控制等一切自动控制语句。结论：通过，无违规、无提示级命中。
- boundary_check_3（知识）：知识证据 ≠ 当前对象诊断事实；禁止「当前番茄已经出现生理问题」「确诊」「确定性处置指令」。结论：通过，无违规、无提示级命中。
- boundary_check_4（证据门控）：有什么证据就说到哪里；无天气证据的 run（74 个中 33 个）禁止输出天气预判。结论：通过，无违规、无提示级命中；无天气证据的 run 均如实说明「天气信息不可用」。
- boundary_check_5（追溯）：可溯源、可回放、可对照。结论：通过。提示级命中若干（1 条 i3 记录 LLM 回答未逐条标注证据编号、4 条早期 s5 记录缺 pipeline_log），已在报告中列明。

报告文件：B07/BOUNDARY_CHECK1_REPORT.md ~ BOUNDARY_CHECK5_REPORT.md。

7.3 B08 五轮验证结论

- 第1遍 基线冻结：freeze.py 生成五场景快照，版本锁定。产出 BASELINE_INFO.md（冻结时间 2026-10-31 04:38:42；app_version=B08_baseline_01；model_version=b06-rf-v1；知识 b04_kb_v1）；回放模式输入完全固定。
- 第2遍 正式验证：verify.py 逐场景执行固定提问 + 自动核验。产出 VERIFY_SUMMARY.md：5 场景全部通过，五条 v8 记录字段齐全、可回溯。
- 第3遍 对照溯源：三大证明。产出 TRACE_SUMMARY.md：同题对照通过、真实失败注入通过、单条完整溯源通过（CONTRAST_REPORT.md / FAILURE_REPORT.md / TRACE_FULL.md）。
- 第4遍 回归套件：regress.py 一键重跑 10 案例。产出 REGRESSION_REPORT.md / REGRESSION_SUMMARY.md：10/10 通过；之后任何修改可全量复测防漂移。
- 第5遍 材料固化：竞赛成套材料整理（PPT 文稿、技术文档、视频脚本、README、局限说明，含 SIMULATED / DERIVED_LABEL / MODEL_OUTPUT 三类诚信标签）。该轮产出目录 B08/competition/ 已按项目方要求删除，仓库不再保留；当前仓库基线回到第四遍验收完成后的状态，前四轮产出完好。

另：创新模块（B08/innovate/）基于冻结基线开发，作为独立后置分析工具对 B01~B08 全部存档只读分析；实测 S1/S2/S3 综合可信度 0.90、S4 0.78、S5 0.48（天气失效降分）、回归 degraded 案例 0.42/0.36（证据缺失对应分数下降）；五套边界检查重跑全部通过；汇总见 B08/innovate/INNOVATE_SUMMARY.md。

7.4 验证链路的设计创新

本项目创新不在预测模型本身（B06 是传统 RandomForest，标签为透明规则），而是搭建了一套适配 LLM 环境预警系统的证据合规验证链路，包含五件事：

1）五层独立边界扫描脚本（B07/boundary_check_1.py ~ boundary_check_5.py）：锁死 LLM 输出边界——禁止病害确诊、禁止设备自动控制、禁止编造不存在的证据。扫描器不依赖 LLM 自查，而是独立规则引擎扫全部存档与视图文本，违禁词命中定位到字段路径/行号，报告人审阅（BOUNDARY_CHECK1~5_REPORT.md）。
2）梯度对照场景（S1~S5）设计：控制变量验证系统判断随证据变化而变化——只改历史时序（S2）、只加天气（S3）、只改证据方向（S4）、只断一路证据（S5），证明推理由真实证据驱动，而非 LLM 的自由发挥（CONTRAST_REPORT.md 三组对照的因果链）。
3）固定回归套件：10 个冻结案例（预期 verdict/模型/天气状态固化），python B08/regression/regress.py 一键批量复测，支持后续迭代后防止系统行为漂移（第四遍验收 10/10 通过）。
4）客观差分对比工具（B08/innovate/diff_snap/snap_diff.py）：同场景跨 run 对比 verdict / 趋势斜率 / 可信度 / 证据状态，仅输出数据差异（如 B07 S2 旧 run vs B08 S2 新 run：verdict 相同 attention、斜率相同 +2.92℃、可信度 1.00→0.90），不生成额外主观风险预判话术。
5）静态溯源视图（B08/innovate/trace_view/render_trace.py）：有证据则展示推理链路（verdict → 每条证据的来源/状态/归因方向），无对应证据时如实留白标注「本 run 无证据记录」，不虚构推理过程；归因方向复用 S4 classify_evidence，与 EVIDENCE_TRACE_REPORT.md 保持一致。

8. 部署与运行

8.1 启动方式与依赖环境

- 依赖：Python 3.8+；requirements.txt（fastapi、uvicorn、openai、httpx 等）；B06/requirements.txt（scikit-learn）；LLM 密钥经 .env 配置（LLM_API_KEY，不入库）。
- 前置数据：B02 数据库已生成（python B02/generate.py）、B06 模型已训练（python B06/train.py）。
- B01~B06 统一入口：python B06/run.py 一个进程挂载全部子应用，浏览器访问 http://127.0.0.1:8000（B01 页面在根路径，B02~B06 在 /B02 ~ /B06）。B03/B04/B05 另有独立启动脚本（run.py，各目录附 .bat/.vbs 快捷启动器）。
- B07 命令行：python B07/S1/run.py（S1）、python B07/S2/run.py（S2）、python B07/S3/run.py --baseline/--with_weather（S3）、python B07/S4/run.py --baseline/--with_evidence（S4）、python B07/S5/run.py --fault 故障类型（S5）；各场景 --inspect RUN_ID 回查记录。
- B08：python B08/run.py --freeze（冻结）、--replay --scenario b08_xxx（回放）、--live --scenario s1~s5（真实链路）、--serve（健康检查服务，端口 8010）；python B08/verify.py --all（正式验证）；python B08/regression/regress.py（回归全量重跑）。

8.2 健康检查 /health 接口校验逻辑

B08/run.py build_app() 中的 GET /health 依次校验五项并逐项返回：

1）knowledge_base：B04/knowledge/knowledge_base.json 存在；
2）model：B06/models/b06_model.joblib 存在；
3）database：B02/data/greenmate_b02.db 存在；
4）scenarios：B08/scenarios/ 下至少 5 个场景快照；
5）external_weather_api：对 api.open-meteo.com 发起 2 秒超时的真实探测，返回 ok / error(状态码) / unavailable(异常类型)。

status 三态语义：ok（系统组件就绪且外部 API 可用）、degraded（系统就绪但外部天气 API 异常，影响 live 模式天气证据）、error（系统组件缺失）。响应同时携带 app_version 与 model_version。

8.3 外部天气 API 失败时的降级处理

- 证据层：天气请求异常按 error_type 固化（如 network_error），天气证据 status=unavailable，失败记录保留不隐藏（FAILURE_REPORT.md）。
- 判断层：依赖天气的判断全部受限，verdict 收缩为 attention_weather_missing（或对应受限表述）。
- 解释层：LLM 输出分两块——可判断的方面（历史/知识/模型证据支撑的内容照常给出）+ 因证据受限无法判断的方面（明确写「天气维度缺失……无法评估未来是否降温」）。
- 系统层：其余模块（历史/知识/模型）正常继续运行，不整体崩溃、不编造缺失数据（S5 实验 + 失败注入双线验证；边界检查4 对 33 个无天气证据存档扫描确认无天气预判编造）。
- 健康检查层面：degraded 状态对运维明确提示「live 模式天气证据受影响」。

9. 局限与后续工作

9.1 当前系统不能做什么（如实列出）

1）不能确诊植株病害：系统只输出环境风险提示（高温/低湿/强光等胁迫背景），不判断植株健康状况，不输出疾病名称与确诊结论（边界检查1）。
2）不能下发自动控制指令：不输出自动灌溉/通风/遮阳/开关设备等动作，一切输出仅为提示告知（边界检查2）。
3）不能把知识资料当成当前对象的诊断事实：知识引用只是通用规律，不是对这株番茄的判定（边界检查3）。
4）不能编造没有拿到的证据：天气不可用就说不可用，不靠常识补写天气预判（边界检查4）。
5）不是真实农业监测系统：环境数据为模拟器生成（SIMULATED），模型标签为透明规则推导（DERIVED_LABEL），模型输出仅标记为 MODEL_OUTPUT；全项目未经过真实种植场景验证，不能用于实际生产决策。
6）预测精度有限：B06 为传统机器学习（RandomForest，recall_WATCH=0.52），输出是「值得关注的信号」而非确定结论；短窗口趋势判断受 K09 限制，不能对全天或长期走势做强确定性推断。
7）模型与知识范围有限：知识库仅 9 段（K01~K09），只覆盖温度/湿度/光照等环境管理主题；不含土壤、EC、pH、CO₂、病虫害等维度（FAILURE_REPORT.md 中 LLM 如实列出了这些未评估维度）。

9.2 后续可扩展方向

1）接入真实传感器数据替换模拟器，做真实环境下的链路验证。
2）扩展知识库覆盖范围（土壤、水肥、更多作物），并引入更强的检索方式（需重新评估引用可追溯要求）。
3）扩大模型训练数据窗口与标签口径，评估更长时间窗口的趋势判断（受 K09 限制逻辑约束）。
4）将 B08 回归套件与边界检查接入持续集成，每次修改自动全量复测。
5）面向多作物、多棚室部署的告警与人工复核流程（仍保持「提示不控制」边界）。

附：文档自查清单（对照提纲逐条核对）

1）项目目标与边界：解决什么/不解决什么/为什么选番茄——覆盖位置：第 1 章 1.1~1.3——已覆盖。
2）系统总体结构：B01~B06 能力、B07 组织方式、B08 验证方式——覆盖位置：第 2 章 2.1~2.3——已覆盖。
3）数据与场景：当前数据来源、历史数据组织、S1~S5 条件、scenario_id 固定复现——覆盖位置：第 3 章 3.1~3.4——已覆盖。
4）核心机制：连续状态认知、多源证据组织、可信等级与判断边界（结合真实字段/接口/记录）——覆盖位置：第 4 章 4.1~4.3——已覆盖。
5）模型与知识：B06 输入输出训练版本、B04 来源检索引用规则、两类证据区分——覆盖位置：第 5 章 5.1~5.3——已覆盖。
6）统一运行与运行追踪：run_id 生成、单次运行记录内容、各要素关联——覆盖位置：第 6 章 6.1~6.3——已覆盖。
7）验证方法与结果：S1~S5 对照/失败/回归（真实 run_id、案例编号）、五套边界检查、B08 五轮验证——覆盖位置：第 7 章 7.1~7.3——已覆盖。
8）验证链路的设计创新（含提纲规定的开头说明与五点）——覆盖位置：第 7 章 7.4——已覆盖。
9）部署与运行：启动方式/依赖、/health 校验逻辑、天气 API 失败降级——覆盖位置：第 8 章 8.1~8.3——已覆盖。
10）局限与后续工作：不能做什么、后续方向——覆盖位置：第 9 章 9.1~9.2——已覆盖。
11）引用真实产出文件名（BOUNDARY_CHECKx_REPORT.md、VERIFY_SUMMARY.md、BASELINE_INFO.md 等）——覆盖位置：第 2/3/7 章多处——已覆盖。
12）所有结论与 B07 边界规则一致（不确诊、不控制、不编造）——第 1/4/7/9 章口径一致——已覆盖。
13）不夸大：未宣称通用大模型验证框架，仅面向本番茄环境预警系统——第 7.4 开头明确限定——已覆盖。
14）未编造功能：所有字段、run_id、指标均来自项目内存档与代码——全文——已覆盖。
