# GreenMate B08 基线复现启动文档（README_RUN）

B08 不新增功能、不修改 B07 创新机制：目标是**冻结版本、制作可复现基线**，用于后续回归验证。

- app_version：**B08_baseline_01**
- model_version：**b06-rf-v1**（本轮验证全程锁定，禁止动态切换模型）
- 详细版本说明：见同目录 BASELINE_INFO.md

## 启动流程

### 0. 前置条件

- B02 数据库已有数据（python B02/generate.py）
- B06 模型已训练（python B06/train.py）
- .env 已配置 LLM_API_KEY（live 模式需要）
- B07/S1~S5 实验已完成（冻结快照引用其源 run_id）

### 1. 冻结基线（首次执行一次）

```bash
cd E:\GreenMate\greenmate-final
python B08/freeze.py
```

产出：scenarios/ 五个场景快照（每个绑定 scenario_id）+ BASELINE_INFO.md。
快照固化观测数据、历史时序、天气证据、引用知识与判定快照；冻结后回放不查询任何数据源。

### 2. 回归回放模式（输入完全固定）

```bash
python B08/replay.py --list                          # 列出场景
python B08/replay.py --scenario b08_s3_weather       # 回放单场景
python B08/replay.py --scenario b08_s3_weather --check   # 附加一致性自检
```

回放只读加载快照：不查询 B02、不调用天气 API、不运行模型、不调用 LLM；
重复运行输出完全一致（回归验证可用）。

### 3. 真实链路模式（验证链路与异常退化）

```bash
python B08/run.py --live --scenario s3    # 实时调用天气 API + 模型 + LLM
```

可选场景：s1（稳态）/ s2（漂移）/ s3（天气叠加）/ s4（多源分歧）/ s5（证据退化）。
注意：live 模式会真实调用外部服务并可能推进 B02 数据（实验注入），与回放模式用途不同。

### 4. 健康检查服务（/health + /ask）

```bash
python B08/run.py --serve
# 服务地址 http://127.0.0.1:8010
```

| 端点 | 说明 |
| --- | --- |
| GET /health | 健康检查：系统组件（知识库/模型/数据库/场景快照）与**外部天气 API 连通性**分别探测；status=ok 全部就绪；degraded 系统就绪但外部 API 异常（明确提示）；error 组件缺失 |
| POST /ask | 执行固定提问（真实链路），body: {"scenario": "s3"}；生成独立 run_id，返回 run_id/verdict/model_version |

健康检查返回示例：

```json
{
  "status": "ok",
  "app_version": "B08_baseline_01",
  "model_version": "b06-rf-v1",
  "checks": {
    "knowledge_base": "ok",
    "model": "ok",
    "database": "ok",
    "scenarios": "ok",
    "external_weather_api": "ok"
  }
}
```

## 端口说明

B08 服务使用 **8010** 端口，与 B01~B06 的 8000 端口互不冲突，可同时运行。

## 复现核对清单

- [ ] python B08/freeze.py 无报错，scenarios/ 有 5 个 b08_*.json
- [ ] BASELINE_INFO.md 中 app_version=B08_baseline_01、model_version=b06-rf-v1
- [ ] 同一场景回放两次输出完全一致（python B08/replay.py --scenario b08_s1_steady）
- [ ] GET /health 返回 status=ok 或 degraded（外部 API 异常时明确提示）
- [ ] POST /ask 返回独立 run_id 且携带 model_version 版本标记
