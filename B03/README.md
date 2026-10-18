# GreenMate B03 · 天气证据（weather_evidence）

接入**真实天气 Web API**，每次查询都真实发起 HTTP 请求（不写死 JSON），把 API 返回转换为结构化的 `weather_evidence` 证据：记录来源、retrieved_at、status/error，成功与失败都生成证据并持久化。

- 技术栈：Python + httpx + FastAPI + HTML + 少量 JS（无 ML / RAG / 真实传感器）
- 访问地址：http://127.0.0.1:8000/B03（B01 `/`、B02 `/B02` 同端口共存，前面模块代码零改动）
- Provider：Open-Meteo（默认，无需 Key，真实联网）；QWeather（可选，完整认证流程）

## 快速开始（项目根目录）

```bash
# 启动（一个进程同时提供 B01 + B02 + B03）
python B03/run.py

# 浏览器打开 http://127.0.0.1:8000/B03
# 输入 location（北京 / 上海 / 广州 / 39.9,116.4）→ 获取天气证据
```

> 无任何必填配置：默认 Open-Meteo 无需 API Key 即可真实联网查询。
> 可选：复制 B03/.env.example 为 .env 切换 provider / 超时 / Key（改后无需重启）。

## weather_evidence 结构

```jsonc
{
  "evidence_type": "weather_evidence",
  "data_source": "external_api",        // 外部真实信息（区别于本地历史/LLM上下文）
  "provider": "open_meteo",
  "query": { "location": "北京", "language": "zh", "requested_at": "..." },
  "resolved": { "name": "北京 / 北京市 / 中国", "latitude": 39.91, "longitude": 116.40 },
  "retrieved_at": "2026-10-16 01:52:24",
  "status": "success",                  // success | error
  "weather": { "temperature_c": 16.7, "humidity_pct": 52, "weather_code": 3,
               "weather_text": "阴", "wind_speed_kph": 6.7, "local_time": "..." },
  "latency_ms": 2335,
  "raw_response": "{...API 原始返回（截断1500字符，可审计）...}",
  "api_url": "https://api.open-meteo.com/..."
}
// 失败时：status="error" + "error": {"error_type","message","http_status","detail"}
```

错误分类（统一映射，绝不伪装成功）：`timeout` / `http_429` / `auth_error` / `network_error` / `not_found` / `api_error` / `config_error` / `validation_error` / `unknown`

## 数据分层（本地历史与外部数据分开）

| 数据 | 位置 | 标记 |
| --- | --- | --- |
| LLM 上下文状态（B01） | 服务端内存 states.py | SIMULATED（内存态） |
| 本地模拟历史（B02） | B02/data/greenmate_b02.db | SIMULATED（30 分钟网格） |
| **外部真实天气（B03）** | **B03/data/weather_evidence.db** | **external_api** |

B03 代码只读外部 API 与自己独立的 evidence 库，不触碰 B01/B02 的数据。

## 目录结构

```
B03/
├── run.py              # 统一启动入口（挂 /、/B02、/B03，不改 B01/B02 代码）
├── app.py              # FastAPI 子应用（/api/weather、/api/evidence、/api/config）
├── weather_client.py   # 真实 HTTP 客户端：认证/超时/异常映射、weather_evidence 组装
├── evidence_store.py   # evidence 持久化（独立 SQLite）
├── static/index.html   # 页面（查询、证据展示、历史、日志）
├── .env.example
├── tests/
│   ├── test_weather_a.py   # TestA：改变查询条件（location）
│   ├── test_weather_b.py   # TestB：只改参数（timeout）
│   ├── test_failures.py    # 异常测试（超时/429/401/403/网络/未找到/转换）
│   └── mock_server.py      # 本地异常注入测试桩（仅测试用）
├── data/weather_evidence.db
└── docs/TEST_RECORDS.md
```

## API（挂载于 /B03）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /B03 | 页面 |
| GET | /B03/api/weather?location=北京&language=zh | **真实调用外部 API**，返回 weather_evidence 并入库 |
| GET | /B03/api/evidence?limit=20 | 外部证据历史（独立存储） |
| GET | /B03/api/config | provider / 超时 / Key 是否配置（脱敏） |

## 测试（已实测，见 docs/TEST_RECORDS.md）

```bash
python B03/tests/test_weather_a.py                 # TestA：改变查询条件（默认 北京 vs 上海）
python B03/tests/test_weather_b.py                 # TestB：只改 timeout，天气数据应一致
python B03/tests/test_failures.py                  # 异常测试（本地桩，无需联网）
```

| 测试 | 内容 | 断言 |
| --- | --- | --- |
| TestA | 改变查询条件（location 北京→上海） | 证据随真实返回变化：解析地点不同、数值不同 |
| TestB | 只改非查询参数（timeout 10s→3s） | 天气数值完全一致（证明结果只依赖查询条件） |
| 异常 | 超时 / 429 / 401 / 403 / 未找到 / 网络 / QWeather 认证 / 缺 Key | error_type 分类正确，失败同样生成证据 |

## 认证 / 超时 / 异常处理

- 认证：Open-Meteo 无需 Key；QWeather 走 `WEATHER_API_KEY`，无 Key → `config_error`，错 Key → `auth_error`（401/403 均识别）
- 超时：`WEATHER_TIMEOUT`（默认 10s），超时 → `timeout`
- 限流：HTTP 429 → `http_429`（明确提示降频）
- 网络异常：连接失败 → `network_error`；全部失败场景都生成结构化 weather_evidence，不抛出裸异常、不伪装成功
- 测试注入：`WEATHER_BASE_URL` / `WEATHER_GEOCODE_BASE_URL` / `WEATHER_QWEATHER_BASE_URL` 可指向本地桩复现失败场景（业务代码零硬编码，桩数据仅存在于 tests/mock_server.py）

## 复现说明

他人复现：`python B03/run.py` → 打开 /B03 → 输入不同 location 查询 → 跑三个测试脚本。失败场景复现：`python B03/tests/test_failures.py`（内置本地桩，无需外网）。
