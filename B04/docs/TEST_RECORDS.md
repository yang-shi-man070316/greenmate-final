# GreenMate B04 测试记录

## 测试环境

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-10-16 |
| OS | Windows 11 Home China (10.0.22000) |
| Python | 3.8.10 |
| 知识库 | B04/knowledge/（8 个本地片段，greenmate_care_guide.md + knowledge_base.json） |
| LLM | 复用根 .env 配置（Test A/B 待真实 Key 后执行） |

## 1. 检索层单元测试（6/6 实测通过，无需 Key）

命令：`python B04/tests/test_retrieval.py`

| 用例 | query | 命中 | 结果 |
| --- | --- | --- | --- |
| 高温干燥处理 | 温度 36 度、湿度 35% 该怎么处理 | K02, K04, K01（含 K04） | PASS ✅ |
| 强光灼伤 | 光照 22000 lux 会不会灼伤 | K03, K06（含 K06） | PASS ✅ |
| SIMULATED 数据源 | SIMULATED 数据源是什么 | K07 | PASS ✅ |
| 库外问题 | 火星土壤的 pH 值 | 空 | PASS ✅ |
| 库外问题+状态（门控） | 火星土壤 pH + 状态 24/65/12000 | 空（状态未注入） | PASS ✅ |
| 状态摘要参与检索 | 当前环境怎么样？+ 36/35/22000 | K04, K01, K02（含 K04） | PASS ✅ |

每条证据均含 source / retrieved_at / scope / score / matched_keywords，可追溯 ✅

## 2. 失败验证（3/3 实测通过，无需 Key）

命令：`python B04/tests/test_failures.py`

| 用例 | 结果 |
| --- | --- |
| 检索为空 + LLM 未配置 → config_error，响应无编造答案内容 | PASS ✅ |
| 库外问题检索为空（检索层不生成伪证据） | PASS ✅ |
| 空问题被 app 层 400 拒绝 | PASS ✅ |

## 3. 端到端验证（实测通过）

- GET /B04 → HTTP 200（页面）
- GET /B04/api/search?q=光照 22000 lux 会不会灼伤 → 命中 K03/K06，证据完整可追溯
- GET /B04/api/search?q=火星土壤pH → count=0，evidence 为空（不编造）
- POST /B04/api/chat（温度 36℃ 问题，未配 Key）→ config_error，无编造答案，knowledge_evidence 正常返回（K01/K02/… 可追溯）
- B01（/）、B02（/B02）、B03（/B03）、B04（/B04）四模块同端口共存，全部 HTTP 200

## 4. Test A / Test B（待真实 LLM Key）

操作：项目根目录 .env 配置 LLM_API_KEY 后执行

```bash
python B04/tests/test_a_knowledge.py      # 带知识 vs 无知识回答对比
python B04/tests/test_b_no_knowledge.py   # 库外问题：必须说明未找到、不编造
```

验收标准：
- Test A：LLM 回答引用检索知识（[依据知识: Kxx] 或片段关键内容），与无知识回答明显不同；
- Test B：回答含「未找到相关知识」，不出现 [依据知识 标注，不编造知识性结论。

## 5. 设计修正记录（检索门控）

初版 build_query 无条件把状态数值（24/65/12000）注入检索 query，导致库外问题
（火星土壤 pH）也被状态数值污染出伪命中，使「检索为空」验收场景不可达。
修正：状态数值仅在问题包含环境相关触发词时才注入（retriever.ENV_TRIGGER_WORDS），
并在检索单测中新增「库外问题+状态」用例固化该行为。
