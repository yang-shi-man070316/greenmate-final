# GreenMate B01

验证一个核心问题：**网页展示的环境状态，AI 是否真的读到了？**

实现方式：环境状态的唯一数据源在服务端内存（states.py），页面通过 API 展示它，提问时服务端把同一份状态 JSON 显式拼进 LLM 上下文。页面显示什么 ≠ AI 读什么——**状态必须放进请求上下文**。

- 技术栈：Python + FastAPI + HTML + 少量原生 JS + LLM API（OpenAI 兼容接口，默认 DeepSeek）
- 不引入：SQLite / RAG / 机器学习 / 真实传感器摄像头
- 模拟环境字段：temperature、humidity、light，source_type=SIMULATED

## 目录结构

```
greenmate-final/
├── main.py                  # FastAPI 入口与路由
├── states.py                # 模拟状态数据（StateA/StateB）与切换逻辑
├── llm.py                   # LLM 封装：读密钥、组上下文、错误映射
├── static/index.html        # 页面（原生 JS，无框架）
├── requirements.txt
├── .env.example             # 密钥配置模板（真实密钥放 .env，不入库）
├── tests/
│   ├── test_llm_direct.py   # 步骤3：单独调通 LLM API
│   ├── run_ab_test.py       # 步骤4：A/B 验收测试（端到端）
│   └── run_failure_tests.py # 步骤5：失败测试（错误密钥/网络异常/缺密钥）
└── docs/
    ├── TEST_RECORDS.md      # 测试记录（失败测试实测 + A/B 复现说明）
    └── AB_TEST_LAST_RUN.md  # A/B 测试每次运行自动生成
```

## 快速开始（Python 3.8+）

```bash
# 1. 安装依赖
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置密钥（不硬编码）：复制模板并填入真实 Key
copy .env.example .env          # Linux/macOS: cp .env.example .env
#    编辑 .env：LLM_API_KEY=sk-你的密钥

# 3. 启动（项目根目录）
python main.py

# 4. 浏览器打开
#    http://127.0.0.1:8000
```

> .env 已被 .gitignore 排除，密钥不会进入版本库。
> 服务运行中修改 .env 无需重启，下一次提问即生效。

## LLM 配置（任意 OpenAI 兼容服务）

| 服务商 | LLM_BASE_URL | LLM_MODEL 示例 |
| --- | --- | --- |
| DeepSeek（默认） | https://api.deepseek.com | deepseek-chat |
| 智谱 GLM | https://open.bigmodel.cn/api/paas/v4 | glm-4-flash |
| Moonshot Kimi | https://api.moonshot.cn/v1 | moonshot-v1-8k |
| 阿里百炼 Qwen | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-plus |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | / | 页面 |
| GET | /api/states | 两组 SIMULATED 状态 + 当前 state_id |
| GET | /api/state | 当前状态（服务端唯一数据源） |
| POST | /api/state/switch | body: {"state_id":"A"\|"B"}，切换状态 |
| POST | /api/chat | body: {"question":"..."}，状态由服务端注入上下文后调 LLM |

错误语义（明确报错，不伪装成功）：

| error_type | HTTP | 含义 |
| --- | --- | --- |
| config_error | 500 | LLM_API_KEY 未配置 |
| auth_error | 502 | 密钥无效（401） |
| network_error | 502 | 无法连接 LLM API |
| api_error | 502 | LLM API 返回错误（如 402 余额不足） |
| timeout | 504 | 请求超时 |

成功响应示例：

```json
{
  "status": "success",
  "answer": "当前环境温度 24℃，湿度 65%，光照 12000 lux……",
  "model": "deepseek-chat",
  "state_used": { "state_id": "A", "source_type": "SIMULATED", "temperature": 24.0, "..." : "送入上下文的状态，与页面展示同源" },
  "messages_sent": [ "实际发给 LLM 的完整上下文，可在页面展开核对" ],
  "elapsed_ms": 1234
}
```

## 核心机制：状态必须放进请求上下文

1. 唯一数据源：服务端内存 states.py（StateA: 24℃/65%/12000lux；StateB: 36℃/35%/22000lux）
2. 页面展示：GET /api/state，只读展示
3. 提问：POST /api/chat，前端只传 question；服务端把当前状态 JSON 拼进 user message（见 llm.build_messages）
4. 核对手段：页面可展开「查看发送给 LLM 的完整上下文」，回答下方回显 AI 读取的状态

## A/B 测试操作说明（验收）

同一问题「当前环境怎么样？」，仅切换环境状态，LLM 输出应随之变化并引用数值。

1. 确认 .env 已配置真实密钥，服务已启动
2. 页面点击 StateA（24℃/65%/12000lux）→ 提问「当前环境怎么样？」→ 记录回答
   - 预期：引用 24℃、65%、12000lux，评价偏舒适
3. 页面点击 StateB（36℃/35%/22000lux）→ 同一问题 → 记录回答
   - 预期：引用 36℃、35%、22000lux，指出高温、低湿、强光并给建议
4. 对比两次回答：仅状态变化、问题不变，回答必须随状态变化并引用数值

一键脚本（自动切换、提问、逐项检查并生成记录）：

```bash
python tests/run_ab_test.py
# 记录自动写入 docs/AB_TEST_LAST_RUN.md
```

## 失败测试操作说明（明确报错，不伪装成功）

| 场景 | 操作 | 页面预期 |
| --- | --- | --- |
| 缺失密钥 | 不配置 LLM_API_KEY | 红色报错：config_error，提示复制 .env.example |
| 错误密钥 | .env 填入错误 Key | 红色报错：auth_error（401） |
| 网络异常 | LLM_BASE_URL 改为 http://127.0.0.1:59999 | 红色报错：network_error |
| 超时 | LLM_TIMEOUT=1 且网络较慢 | 红色报错：timeout（504） |

一键脚本（无需真实密钥；auth_error 用例需联网）：

```bash
python tests/run_failure_tests.py
```

## 测试记录与复现

- 实测记录见 docs/TEST_RECORDS.md（接口自测 + 失败测试实测输出 + A/B 复现步骤）
- 他人复现：安装依赖 → 配置 .env → python main.py → 按「A/B 测试操作说明」执行即可
