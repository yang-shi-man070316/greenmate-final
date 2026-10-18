# GreenMate B03 测试记录

## 测试环境

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-10-16 |
| OS | Windows 11 Home China (10.0.22000) |
| Python | 3.8.10 |
| 外部 API | Open-Meteo（无需 Key，真实联网）；QWeather（认证流程，本地桩验证） |
| 关键依赖 | httpx 0.28.1（fastapi/openai 已有依赖） |

## 1. TestA：改变查询条件（真实 API，实测通过）

命令：`python B03/tests/test_weather_a.py`（北京 vs 上海）

```
location=北京 → 解析: 北京 / 北京市 / 中国 | 温度 16.7℃ | 湿度 52% | 阴 | 风速 6.7 km/h | 2475ms
location=上海 → 解析: 上海 / 上海市 / 中国 | 温度 20.5℃ | 湿度 75% | 基本晴朗 | 风速 8.2 km/h | 1834ms
  [PASS] location=北京 成功获取证据
  [PASS] location=上海 成功获取证据
  [PASS] 解析地点随查询条件变化（北京 ≠ 上海）
  [PASS] location=北京 数值在合理范围（16.7℃ / 52%）
  [PASS] location=上海 数值在合理范围（20.5℃ / 75%）
TestA 结论：通过 ✅（改变查询条件，证据随真实返回变化）
```

## 2. TestB：只改参数（真实 API，实测通过）

命令：`python B03/tests/test_weather_b.py`（location=北京，timeout 10s → 3s）

```
第 1 次（timeout=10s）： 16.7℃ / 52% / 阴 / 6.7 km/h（2114ms）
第 2 次（timeout=3s）：  16.7℃ / 52% / 阴 / 6.7 km/h（2446ms）
  [PASS] 温度一致 16.7 vs 16.7
  [PASS] 湿度一致 52 vs 52
  [PASS] 天气代码一致 3 vs 3
  [PASS] 风速一致 6.7 vs 6.7
  [PASS] 查询条件一致（location=北京）
TestB 结论：通过 ✅（只改参数不改查询条件，天气证据数据一致）
```

## 3. 异常测试（本地桩，9/9 实测通过）

命令：`python B03/tests/test_failures.py`（内置 mock server，真实 HTTP 打到本地桩）

| 用例 | 期望 error_type | 实际 | 结果 |
| --- | --- | --- | --- |
| 超时（桩 /slow + timeout=2s） | timeout | timeout | PASS ✅ |
| 限流 429（桩 /429） | http_429 | http_429（HTTP 429） | PASS ✅ |
| 认证失败 401（桩 /401） | auth_error | auth_error（HTTP 401） | PASS ✅ |
| 无权限 403（桩 /403） | auth_error | auth_error（HTTP 403） | PASS ✅ |
| 地点不存在（桩 /geocode_empty） | not_found | not_found | PASS ✅ |
| 网络异常（未监听端口） | network_error | network_error | PASS ✅ |
| 转换逻辑（桩 /ok → 证据组装） | success | success（温度 12.5℃ / 多云，数值来自桩响应） | PASS ✅ |
| QWeather 认证失败（桩 /v2/city/lookup → 401） | auth_error | auth_error | PASS ✅ |
| QWeather 缺密钥 | config_error | config_error | PASS ✅ |

结论：所有失败场景都生成结构化错误证据（status=error + error_type/message/http_status），未伪装成功。

## 4. 端到端验证（实测通过）

- GET /B03/api/weather?location=北京 → 完整 weather_evidence（data_source=external_api、retrieved_at、latency_ms=2335、raw_response 含 API 真实返回）
- 证据入库：B03/data/weather_evidence.db（独立于 B02 本地模拟历史库）
- GET /B03/api/evidence → 历史列表（total=1，location=北京，status=success）
- B01（/）、B02（/B02）与 B03（/B03）同端口共存，三者数据互不混用

## 5. 复现说明

1. `python B03/run.py` → http://127.0.0.1:8000/B03
2. TestA：`python B03/tests/test_weather_a.py`（可 `--locations 广州 深圳`）
3. TestB：`python B03/tests/test_weather_b.py`（可 `--location 广州`）
4. 异常：`python B03/tests/test_failures.py`（无需外网，内置桩）
