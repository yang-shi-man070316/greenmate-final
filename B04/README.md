# GreenMate B04 · 本地知识增强（检索 evidence 注入 LLM）

在已有 GreenMate 链路上增加**本地知识检索**：问题 + 状态关键词 → 检索本地知识库 Top-K → 知识片段作为 evidence 注入 LLM 上下文，让回答有据可依，而不是凭空生成。

- 边界：只做检索增强——无训练、无微调、无 Embedding、无 RAG 系统改造、**无数据库、无复杂索引**
- 知识来源：**仅本地资料**（B04/knowledge/），不联网
- 访问地址：http://127.0.0.1:8000/B04（B01/B02/B03 同端口共存，前面模块代码零改动）

## 快速开始（项目根目录）

```bash
python B04/run.py            # 一个进程同时提供 B01+B02+B03+B04
# 浏览器打开 http://127.0.0.1:8000/B04
```

LLM 调用复用根目录 .env 的 LLM_API_KEY（与 B01 相同配置，无需重复设置）。

## 工作原理

```
用户问题 + 环境状态（与 B01 同源数值）
        │
        ▼
最小检索（retriever.py）：关键词双向子串打分，Top-K=3，分数 0 不入选
        │  状态数值仅在问题与环境相关时才注入（门控，见下）
        ▼
知识片段 evidence（id / topic / scope / content / source / retrieved_at / score / matched_keywords）
        │
        ▼
注入 LLM 上下文：问题 + 环境状态 + 知识片段 + 推理要求（b04_llm.py）
        │
        ▼
回答（LLM 被强制标注 [依据知识: Kxx] 与 [推断]）+ evidence 随响应返回（可追溯）
```

**状态门控**：仅当问题包含环境相关词（温度/湿度/光照/环境/高温/干燥/强光/养护/怎么样…）时，
状态数值才参与检索；否则只按问题检索。这保证库外问题（如「火星土壤 pH」）真正走到
「检索为空 → 未找到相关知识」路径，而不是被状态数值污染出伪命中。

## 知识库与检索结果记录说明

### 本地知识资料（B04/knowledge/）

- `greenmate_care_guide.md`：知识源文档（人类可读、可编辑），8 个主题章节
- `knowledge_base.json`：结构化片段，每段含 **id / topic / keywords / content / source / scope**，
  source 指向源文档章节标题（可追溯）；scope 分 plant_care / device_guide / troubleshooting

片段清单：K01 温度适宜范围｜K02 湿度适宜范围｜K03 光照强度分级｜K04 高温应对｜
K05 干燥应对｜K06 强光灼伤处理｜K07 SIMULATED 数据源说明｜K08 夜间光照异常排查

### 检索结果记录格式（evidence）

每次检索产生的证据记录如下字段（随 API 响应返回，页面可视化展示）：

| 字段 | 说明 |
| --- | --- |
| id | 片段编号（K01–K08），回答中引用标注使用 |
| topic / scope | 主题 / 适用范围分类 |
| content | 片段内容（送入 LLM 上下文的知识正文） |
| source | 来源文件+章节（如 knowledge/greenmate_care_guide.md#高温应对） |
| retrieved_at | 检索时间 |
| score / matched_keywords | 匹配得分与命中关键词（解释为什么检索到它） |

无命中时 evidence 为空列表，系统**不生成任何伪证据**。

## API（挂载于 /B04）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /B04 | 页面 |
| GET | /B04/api/knowledge | 知识库概览（片段列表） |
| GET | /B04/api/search?q=&top_k= | **仅检索**（不调 LLM），返回可追溯证据 |
| POST | /B04/api/chat | body: {question, state_id}，检索 → 注入 → LLM，返回 answer + knowledge_evidence + messages_sent |
| GET | /B04/api/states | 可选模拟状态（与 B01 同源数值，只读复用） |

chat 响应：`status=success`（有知识）/ `no_knowledge`（检索为空，LLM 必须说明未找到）/ `error`（失败，不编造）。

## 测试

```bash
python B04/tests/test_retrieval.py        # 检索层单测（无需 key/网络）
python B04/tests/test_failures.py         # 失败验证（无需 key/网络）
python B04/tests/test_a_knowledge.py      # Test A：需真实 LLM_API_KEY
python B04/tests/test_b_no_knowledge.py   # Test B：需真实 LLM_API_KEY
```

| 测试 | 场景 | 断言 |
| --- | --- | --- |
| Test A | 库内有相关内容（36℃/35% 处理） | 检索命中 K04 等；LLM 回答引用知识（[依据知识: Kxx] 或片段关键内容）；与无知识回答明显不同 |
| Test B | 库内无相关内容（火星土壤 pH） | 检索为空；LLM 明确说明「未找到相关知识」；无伪造引用；不编造结论 |
| 失败验证 | 检索为空 + LLM 未配置 | 返回 config_error，响应中无任何编造答案；空问题被 400 拒绝 |
| 检索单测 | 6 用例 | 命中/排序/可追溯字段/门控/空结果，全部可离线复现 |

## 验收对照

| 验收点 | 实现 |
| --- | --- |
| 同一问题加知识后回答更贴近知识内容 | Test A：带知识回答引用 K04（遮阴/通风/加湿），与无知识回答不同 |
| 移除知识/知识不存在时降级 | 检索为空 → LLM 被 system prompt 强制先说「未找到相关知识」，推断必须标注 [推断] |
| 检索可追溯 | evidence 含 source / retrieved_at / scope / content，页面逐条展示 |
| 区分知识与推断 | 回答内 [依据知识: Kxx] / [推断] 标注 + 响应结构上 evidence 与 answer 分离 |
| 禁止伪造引用 | 无知识时禁止出现 [依据知识 标注；system prompt 明确「不得虚构引用」 |

## 复现说明

他人复现：`python B04/run.py` → /B04 页面提问（默认问题命中高温知识）→ 跑 4 个测试脚本。
Test A/B 需先在 .env 配置 LLM_API_KEY（检索层与失败验证不依赖 Key，可离线复现）。
