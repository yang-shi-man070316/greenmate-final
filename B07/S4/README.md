# GreenMate B07/S4 · 多源证据分歧推理（命令行）

终端运行（无网页）的**分歧场景**实验：B02 持续升温 + B06 WATCH 指向风险，B03 未来降温提示可能缓解，B04 专业知识提示「趋势不能证明未来一定恶化」——多源证据**不强行合并成单一确定结论**，输出三段式合成推理，每条结论绑定证据、可反向查询依据。

- 复用：B05 工具（get_weather_forecast → B03、search_tomato_knowledge → B04），B06 已训模型（不重训，真实输出 WATCH 0.955），B01 LLM 能力
- 不重写底层工具逻辑；B03 预报新增 temperature_2m 字段（向后兼容）；B04 知识库新增 K09「高温趋势判断限制」片段

## 使用（项目根目录）

```bash
python B07/S4/run.py --baseline         # 仅内部 B02+B06 证据 → run_id
python B07/S4/run.py --with_evidence    # 叠加 B03 天气 + B04 知识 → run_id + 两轮对比
python B07/S4/run.py --compare          # 两轮对比
python B07/S4/run.py --inspect RUN_ID   # 读记录（含反向查询：结论依据哪些证据）
python B07/S4/tests/test_s4.py          # 测试（无需 LLM Key / 无需联网）
```

## 固定分歧场景（实测 2026-10-22）

| 证据 | 数据源 | 内容 | 方向 |
| --- | --- | --- | --- |
| E1 | B02 历史时序 | 10-08 11:30~14:30 持续升温 26.3→38.1℃ | 支持提高关注 |
| E2 | B06 模型 | WATCH（概率 0.955，真实输出未修改） | 支持提高关注 |
| E3 | B03 天气 | 未来 3 小时降温 30→27→24℃（场景桩，provider=open_meteo） | 可能缓解/反向 |
| E4 | B04 知识 | K09：持续高温值得关注，但不能证明未来一定继续恶化 | 不足以确定 |

**两轮判定**：baseline=attention（内部一致指向风险）；with_evidence=**attention_uncertain**（关注但存在缓解信号与不确定性）。变化归因：新增 B03/B04 多源证据，内部证据与判定输入完全未变。

## 核心设计

1. **统一证据字段**：[evidence.py](B07/S4/evidence.py) 每条证据含 source_type/source/time/status/result/error；status 仅 ok/unavailable/error；**RAG 无匹配属于 ok**（工具正常完成）；专属扩展：B03 加 provider/forecast_time，B04 加 citation，B06 加 model_version
2. **工具调用 ≠ 结果采用**：pipeline_log 记录四层状态（tool_called → tool_success → converted_to_evidence → adopted_in_judgment）；采用条件独立判定（如 forecast_time 校验失败 → 调用成功但未采用），baseline 模式 B03/B04 工具不调用
3. **三段式合成**（[judgment.py](B07/S4/judgment.py)）：支持提高关注的证据 / 提示情况可能缓解、反向变化的证据 / 当前信息不足以确定的部分；每条结论绑定证据编号（E1~E4），`explain_conclusion` 支持反向回答「这句话主要依据哪些证据」
4. **幻觉约束**（[llm_explain.py](B07/S4/llm_explain.py)）：prompt 强制三部分输出 + 证据标注 + 禁止「一定/必然/肯定/绝对/无疑/必将/注定」；`check_forbidden` 校验输出（否定语境如「不能证明……一定……」不算命中——实测修复过该误报）

## 实测中的修复

- 初版 check_forbidden 把 LLM 引用 K09 原文「不能证明未来一定继续恶化」中的「一定」误判为违规；已改为排除否定语境，并新增测试固化
- B06 对 S2 漂移段输出 NORMAL（0.92），不满足任务书「B06 输出 WATCH」场景；实测探测后选用热浪 ramp 段（10-08 11:30~14:00）作为固定内部窗口，模型真实输出 WATCH 0.955——场景数据与模型输出完全真实，无任何伪造

## 目录结构

```
B07/S4/
├── run.py             # 主入口（--baseline / --with_evidence / --compare / --inspect）
├── evidence.py        # 统一证据封装（字段/status 语义/工具层映射）
├── judgment.py        # 分歧判定 + 三部分合成 + 反向查询
├── llm_explain.py     # 三段式 LLM 推理（证据绑定 + 禁止词校验）
├── weather_stub.py    # 未来降温预报场景桩
├── run_records/       # s4- 前缀运行记录
├── tests/test_s4.py   # 19 项测试
└── README.md
```
