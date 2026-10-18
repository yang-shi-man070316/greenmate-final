# GreenMate B01 测试记录

## 测试环境

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-10-14 |
| OS | Windows 11 Home China (10.0.22000) |
| Python | 3.8.10 |
| fastapi | 0.124.4 |
| uvicorn | 0.33.0 |
| openai | 1.109.1 |
| httpx | 0.28.1 |
| python-dotenv | 1.0.1 |
| LLM 服务 | DeepSeek API（OpenAI 兼容），模型 deepseek-chat |

## 1. 接口自测（无密钥，实测通过）

| 用例 | 请求 | 结果 |
| --- | --- | --- |
| 页面可访问 | GET / | HTTP 200，返回页面 |
| 状态列表 | GET /api/states | 200，返回 StateA(24/65/12000)、StateB(36/35/22000)，source_type=SIMULATED，current_state_id=A |
| 当前状态 | GET /api/state | 200，返回 StateA |
| 切换 A→B | POST /api/state/switch {"state_id":"B"} | 200，返回 StateB（36/35/22000） |
| 切换 B→A | POST /api/state/switch {"state_id":"A"} | 200，返回 StateA（24/65/12000） |
| 非法状态 | POST /api/state/switch {"state_id":"X"} | 400，"未知状态: X，可选: A, B" |
| 无密钥提问 | POST /api/chat {"question":"当前环境怎么样？"} | 500，error_type=config_error，明确提示配置 LLM_API_KEY |

## 2. 失败测试（步骤5，实测通过——明确报错，不伪装成功）

### 2.1 E2E 经 HTTP（故障注入实例）

- 错误密钥（实例端口 8001，LLM_API_KEY=sk-...000000）：

```json
{"error_type":"auth_error","message":"LLM API 认证失败（401）：API Key 无效或已过期，请检查 .env 中的 LLM_API_KEY","detail":"AuthenticationError: Error code: 401 - {'error': {'message': 'Authentication Fails, Your api key: ****0000 is invalid (request_id: ...)'...","elapsed_ms":399,"status":"error"}
```
HTTP 502 ✅（真实请求 DeepSeek API 得到 401，错误信息如实透传）

- 网络异常（实例端口 8002，LLM_BASE_URL=http://127.0.0.1:59999）：

```json
{"error_type":"network_error","message":"网络异常：无法连接 LLM API（base_url=http://127.0.0.1:59999），请检查网络或 LLM_BASE_URL","detail":"APIConnectionError: [WinError 10061] 由于目标计算机积极拒绝，无法连接。","elapsed_ms":2241,"status":"error"}
```
HTTP 502 ✅

- 页面行为：以上错误在页面回答区红色显示真实 error_type 与 message，日志面板如实记录，绝无假成功。

### 2.2 python tests/run_failure_tests.py 原始输出

```
用例：错误密钥（预期 auth_error，需联网：真实请求 DeepSeek API 得到 401）
  期望 error_type: auth_error | 实际: auth_error
  消息: LLM API 认证失败（401）：API Key 无效或已过期，请检查 .env 中的 LLM_API_KEY
  详情: AuthenticationError: Error code: 401 - {'error': {'message': 'Authentication Fails, Your api key: ****0000 is invalid ...
  结论: PASS ✅

用例：网络异常（预期 network_error，指向本机未监听端口，无需联网）
  期望 error_type: network_error | 实际: network_error
  消息: 网络异常：无法连接 LLM API（base_url=http://127.0.0.1:59999），请检查网络或 LLM_BASE_URL
  详情: APIConnectionError: [WinError 10061] 由于目标计算机积极拒绝，无法连接。
  结论: PASS ✅

用例：缺失密钥（预期 config_error，无需联网）
  期望 error_type: config_error | 实际: config_error
  消息: LLM_API_KEY 未配置：请复制 .env.example 为 .env 并填入真实 API Key
  结论: PASS ✅

失败测试总结论：全部通过 ✅（所有失败场景都明确报错，未伪装成功）
```

## 3. A/B 测试（步骤4，验收）

### 3.1 复现操作说明

1. 复制 `.env.example` 为 `.env`，填入真实 `LLM_API_KEY`（服务运行中修改无需重启）
2. `python main.py` 启动，浏览器打开 http://127.0.0.1:8000
3. 页面点击 StateA（24℃/65%/12000lux）→ 提问「当前环境怎么样？」→ 记录回答
   - 预期：引用 24℃、65%、12000lux，评价偏舒适
4. 页面点击 StateB（36℃/35%/22000lux）→ 同一问题 → 记录回答
   - 预期：引用 36℃、35%、22000lux，指出高温、低湿、强光并给建议
5. 对比：仅状态变化、问题不变，回答必须随状态变化并引用数值 → 验收通过

一键脚本（自动切换 → 提问 → 逐项检查 → 生成记录）：

```bash
python tests/run_ab_test.py
# 记录自动写入 docs/AB_TEST_LAST_RUN.md
```

### 3.2 验收标准

| 检查项 | 标准 |
| --- | --- |
| 回答随状态变化 | StateA 与 StateB 回答内容不同 |
| StateA 引用数值 | 回答包含 24 / 65 / 12000 |
| StateB 引用数值 | 回答包含 36 / 35 / 22000 |
| 仅切换状态 | 问题文本不变，仅服务端状态切换 |

### 3.3 实测结果

待填入真实密钥后执行（本机实测记录见 docs/AB_TEST_LAST_RUN.md）。

## 4. 上下文核对（步骤3）

python tests/test_llm_direct.py 打印的实际发送内容（无密钥时仍可核对组装结果）：

```
[system]
你是 GreenMate 智能环境助手。...（规则：必须基于给定状态并引用数值）

[user]
当前环境状态如下（数据来源：SIMULATED）：
{
  "state_id": "A",
  "label": "StateA",
  "source_type": "SIMULATED",
  "temperature": 24.0,
  "temperature_unit": "°C",
  "humidity": 65.0,
  "humidity_unit": "%",
  "light": 12000.0,
  "light_unit": "lux"
}

用户问题：当前环境怎么样？
```

状态以 JSON 文本显式放入请求上下文 ✅
