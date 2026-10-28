"""S4 统一证据封装：每一条证据基础字段 source_type / source / time / status / result / error。

status 语义（任务书规定）：
- ok          工具正常完成调用（RAG 检索无匹配结果也属于 ok）
- unavailable  当前数据源暂时无法取得
- error        参数、程序调用过程本身发生错误

各数据源保留专属扩展字段：
- B03 天气：provider、forecast_time
- B04 知识：citation（source 引用）
- B06 模型：model_version

注意与 B05 工具层 status 的语义差异：B05 的 search_tomato_knowledge 无匹配返回
unavailable（工具层语义），S4 证据层将其映射为 ok（工具正常完成、只是无匹配）——
工具被调用 ≠ 工具结果被采用，两层状态分开记录。
"""

from datetime import datetime

ALLOWED_STATUS = ("ok", "unavailable", "error")

# B05 工具层 no_match/no_data（工具正常工作但无匹配数据）→ 证据层 ok
_TOOL_TO_EVIDENCE_STATUS = {
    "ok": "ok",
    "unavailable": "ok",   # no_match / no_data：工具正常完成，只是无匹配结果
    "error": "error",
}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def wrap(source_type, source, status, result=None, error=None, **extra):
    """构造统一证据。status 必须为 ok/unavailable/error。"""
    if status not in ALLOWED_STATUS:
        raise ValueError("非法证据 status：%s（仅允许 %s）" % (status, ALLOWED_STATUS))
    ev = {
        "source_type": source_type,
        "source": source,
        "time": now_str(),
        "status": status,
        "result": result,
        "error": error,
    }
    ev.update(extra)
    return ev


def from_tool(source_type, source, tool_result, **extra):
    """把 B05 工具统一返回模板转换为 S4 证据（status 语义按证据层映射）。"""
    tool_status = (tool_result or {}).get("status", "error")
    status = _TOOL_TO_EVIDENCE_STATUS.get(tool_status, "error")
    if tool_status == "ok":
        return wrap(source_type, source, status, result=tool_result.get("data"), **extra)
    # unavailable（无匹配/无数据）→ 证据层 ok，result 记录"无匹配结果"信息；error 保持 error
    return wrap(source_type, source, status,
                result={"no_match": True, "note": (tool_result.get("error") or {}).get("message", "")}
                if status == "ok" else None,
                error=tool_result.get("error") if status == "error" else None,
                **extra)
