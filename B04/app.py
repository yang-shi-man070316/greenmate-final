"""B04 FastAPI 子应用：本地知识检索增强问答（挂载于 /B04，见 run.py）。

流程：问题 + 状态关键词 → 本地检索 Top-K → 知识片段作为 evidence 注入 LLM 上下文。
边界：不引入数据库/索引/Embedding；检索为空时 LLM 必须说明「未找到」，不编造。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from b04_llm import ask_with_knowledge
from retriever import build_query, load_segments, retrieve
from states import STATES  # 只读复用 B01 模拟状态（不修改 B01 代码）

STATIC_DIR = Path(__file__).resolve().parent / "static"

b04_app = FastAPI(title="GreenMate B04 — 知识增强")


class ChatRequest(BaseModel):
    question: str
    state_id: str = "A"


@b04_app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@b04_app.get("/api/knowledge")
def knowledge():
    """本地知识库概览（片段列表，可追溯 source）。"""
    return {"name": "greenmate_b04_knowledge_base", "local_only": True,
            "segments": load_segments()}


@b04_app.get("/api/search")
def search(q: str = "", top_k: int = 3):
    """仅检索（不调 LLM），返回可追溯的检索证据，供调试与验证。"""
    evidence = retrieve(q, top_k=max(1, min(top_k, 8)))
    return {"query": q, "count": len(evidence),
            "evidence": evidence,
            "note": "无命中时 evidence 为空，系统不得编造"}


@b04_app.post("/api/chat")
def chat(req: ChatRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    state = STATES.get((req.state_id or "A").strip().upper(), STATES["A"])

    # 1. 最小检索：问题 + 状态关键词 → Top-K 知识片段（可追溯）
    query = build_query(question, state)
    evidence = retrieve(query, top_k=3)

    # 2. 知识片段注入 LLM 上下文（问题 + 知识 + 推理要求）
    result = ask_with_knowledge(question, state, evidence)

    # 3. 检索证据随响应返回（source / retrieved_at / scope / content 可追溯）
    result["knowledge_evidence"] = evidence
    result["retrieval_query"] = query
    result["state_used"] = state
    if result.get("status") == "success":
        # 检索为空时标记 no_knowledge：回答必须说明未找到，不编造结论
        result["status"] = "success" if evidence else "no_knowledge"
    if not evidence:
        result["has_knowledge"] = False
    return result


@b04_app.get("/api/states")
def api_states():
    """可选模拟状态（与 B01 同源数值，只读）。"""
    return {"states": list(STATES.values())}


b04_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="b04_static")
