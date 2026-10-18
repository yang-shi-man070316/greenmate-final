"""B05 FastAPI 子应用：工具智能体（挂载于 /B05，见 run.py）。

POST /api/agent：完整 Agent 闭环（LLM 自主 tool_call → 真实执行 → tool_result → 最终回答），
返回每一步调用日志（tool_call / execution / tool_result），页面可视化整条链路。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import run_agent
from states import STATES, current_state, switch_state
from tools import TOOL_META

STATIC_DIR = Path(__file__).resolve().parent / "static"

b05_app = FastAPI(title="GreenMate B05 — 工具智能体")


class AgentRequest(BaseModel):
    task: str


class SwitchRequest(BaseModel):
    state_id: str


@b05_app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@b05_app.get("/api/tools")
def list_tools():
    """4 个标准工具清单（Agent 可调用）。"""
    return {"count": len(TOOL_META),
            "tools": [{"name": n, "description": m["description"], "parameters": m["parameters"]}
                      for n, m in TOOL_META.items()],
            "note": "工具真实执行，返回结构 {status: ok|unavailable|error, source, provider, retrieved_at, data?, error?}"}


@b05_app.get("/api/current_state")
def api_current_state():
    """当前环境状态（只读，供页面展示；Agent 通过工具获取同一数据源）。"""
    return current_state()


@b05_app.get("/api/states")
def api_states():
    """可选模拟状态列表（与 B01 同源数据）。"""
    return {"states": list(STATES.values()), "current_state_id": current_state()["state_id"]}


@b05_app.post("/api/state/switch")
def api_switch_state(req: SwitchRequest):
    """切换当前状态（与 B01 同一份服务端状态，切换后 Agent 工具立即读到新状态）。"""
    try:
        return switch_state(req.state_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@b05_app.post("/api/agent")
def agent(req: AgentRequest):
    """执行 Agent 完整闭环，返回调用链路日志与最终回答。"""
    result = run_agent(req.task)
    if result.get("status") == "error":
        # 配置/网络类错误如实返回（HTTP 502），不伪装成功
        return result  # 前端按 status 字段渲染错误
    return result


b05_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="b05_static")
