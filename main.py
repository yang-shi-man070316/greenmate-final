"""GreenMate B01 — FastAPI 入口。

核心原则（本任务验收点）：
- 环境状态的唯一数据源是服务端内存中的 current_state（states.py）；
- 页面展示的状态通过 /api/state 获取，与送入 LLM 上下文的是同一份数据；
- 提问时由服务端把当前状态 JSON 显式拼进 LLM 上下文，前端不传状态、无法伪造。

运行（项目根目录）：python main.py
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from llm import ask_llm
from states import STATES, current_state, switch_state

app = FastAPI(title="GreenMate B01")

# 错误类型 -> HTTP 状态码：明确报错，不伪装成功
ERROR_HTTP_CODES = {
    "config_error": 500,
    "auth_error": 502,
    "network_error": 502,
    "api_error": 502,
    "timeout": 504,
    "unknown": 502,
}


class SwitchRequest(BaseModel):
    state_id: str


class ChatRequest(BaseModel):
    question: str


@app.get("/")
def index():
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))


@app.get("/api/states")
def list_states():
    return {"states": list(STATES.values()), "current_state_id": current_state()["state_id"]}


@app.get("/api/state")
def get_state():
    return current_state()


@app.post("/api/state/switch")
def api_switch_state(req: SwitchRequest):
    try:
        return switch_state(req.state_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/chat")
def chat(req: ChatRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    state = current_state()  # 与页面展示同源的服务端状态
    result = ask_llm(state=state, question=question)  # 状态显式放进 LLM 上下文

    if result.get("status") == "error":
        # 返回真实错误类型与信息，绝不伪装成功
        code = ERROR_HTTP_CODES.get(result.get("error_type"), 502)
        return JSONResponse(status_code=code, content=result)
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
