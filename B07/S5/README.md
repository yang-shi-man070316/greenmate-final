# GreenMate B07/S5 · 证据退化实验（命令行）

**单证据失效实验**：基线（全部证据正常）vs 故障（同一时间只触发一种故障，故障后不修复），
复用同一固定提问，验证系统「不整体崩溃、不伪造信息、利用剩余证据推理、清晰标注局限」。

- 约束：不新增模块（全部复用 S4 组件：evidence / judgment 分类 / weather_stub / 内部证据加载 + B05 工具 + B06 模型 + B01 LLM 能力）
- 交付：实验脚本 + [EXPERIMENT_REPORT.md](B07/S5/EXPERIMENT_REPORT.md)

## 使用（项目根目录）

```bash
python B07/S5/run.py --baseline                          # 基线：全部证据正常 → run_id 对照组
python B07/S5/run.py --fault weather_unavailable          # 故障1：天气 API 不可用
python B07/S5/run.py --fault rag_insufficient             # 故障2：RAG 检索不足
python B07/S5/run.py --fault tool_error                   # 故障3：工具返回异常
python B07/S5/run.py --report                             # 生成 EXPERIMENT_REPORT.md（基线 vs 最新故障轮）
python B07/S5/run.py --inspect RUN_ID                     # 读取记录
python B07/S5/tests/test_s5.py                            # 测试（无需 LLM Key / 无需联网）
```

## 三种单一故障（真实触发，不伪造）

| 故障参数 | 触发方式 | 失效证据 | 证据状态 |
| --- | --- | --- | --- |
| weather_unavailable | 天气请求指向未监听端口（真实网络失败） | E3 天气 | error（network_error） |
| rag_insufficient | 库外查询词（无匹配） | E4 知识 | ok + no_match（检索不足） |
| tool_error | 天气工具传非法参数 | E3 天气 | error（validation_error） |

## LLM 两块式输出（强制）

- **【可判断内容】**：基于剩余有效证据尽力推理，每条标注证据编号（[E1][E2][E4-K01]…），禁止直接回复「无法分析」
- **【受限说明】**：清晰写明哪一项证据缺失、缺失原因、哪些判断因此不可靠，禁止编造缺失数据

## 实测结果（2026-10-27，故障：weather_unavailable）

| 维度 | 基线 | 故障后 |
| --- | --- | --- |
| 有效证据 | E1 E2 E3 E4 | E1 E2 E4（E3 缺失） |
| verdict | attention_uncertain | **attention_weather_missing** |
| 消失信息 | — | 未来天气（降温/缓解方向）：无法评估未来几小时温度是否回落、是否降雨缓解、夜间条件 |
| 保留判断 | 升温历史 + 模型 WATCH + K09 知识 → 继续给出关注与防护建议 | 同左（未整体放弃推理） |
| 受限说明 | — | LLM 明确列出「因 E3 缺失而不可靠的判断」+「判断仅反映 11:30–14:30 实测窗口」 |

验收结论 ✅：系统未崩溃、未伪造天气数据、利用剩余证据完成推理、局限标注清晰。
报告含「证据参与度检查」：基线回答对天气证据的提及次数 → 判断该证据是否真正参与推理
（若故障前后输出差别很小，报告会提示排查）。

## 目录结构

```
B07/S5/
├── run.py               # 主入口（--baseline / --fault / --report / --inspect）
├── s5_judgment.py       # 退化判定（有效/缺失证据区分 + verdict 规则）
├── s5_llm_explain.py    # 两块式 LLM 推理
├── run_records/         # s5- 前缀运行记录
├── tests/test_s5.py     # 16 项测试
├── EXPERIMENT_REPORT.md # 实验报告（--report 生成）
└── README.md
```
