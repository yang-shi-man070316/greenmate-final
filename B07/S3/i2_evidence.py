"""创新点2 证据封装（B07/S3 交付物）：信息 → 可追溯证据。

四类证据的作用不可互相替代（ROLE_BOUNDARIES）：
- B02 历史（internal_history）：已发生事实——只回答「已经发生了什么」，不能推断未来；
- B03 天气（external_weather）：外部潜在条件——外部环境预报，是潜在影响因素而非环境内部事实；
- B04 专业知识（local_knowledge）：通用专业判断——只提供通用规则，不针对本次具体观测下结论；
- B06 预测（ml_prediction）：对未来窗口的推断——模型推断，不是已发生事实，可能出错。

每条证据必须自带元信息：source、time、status、result；按需补充 error、citation、model_version。
每条证据必须能回答五问：是什么证据、来源、获取时间、是否有效、内容是什么。
"""

from datetime import datetime

SOURCE_TYPES = ("internal_history", "external_weather", "local_knowledge", "ml_prediction")
ALLOWED_STATUS = ("ok", "unavailable", "error")

ROLE_BOUNDARIES = {
    "internal_history": {
        "name": "B02 历史时序",
        "role": "已发生事实",
        "boundary": "只回答「已经发生了什么」，不能推断未来、不能替代预测",
        "extra_fields": [],
    },
    "external_weather": {
        "name": "B03 天气",
        "role": "外部潜在条件",
        "boundary": "只提供外部环境条件（预报），是潜在影响因素而非环境内部事实",
        "extra_fields": ["provider", "forecast_time"],
    },
    "local_knowledge": {
        "name": "B04 专业知识",
        "role": "通用专业判断",
        "boundary": "只提供通用专业规则，不针对本次具体观测做判断",
        "extra_fields": ["citation"],
    },
    "ml_prediction": {
        "name": "B06 模型预测",
        "role": "对未来窗口的推断",
        "boundary": "只是模型推断（下一窗口），不是已发生事实，可能出错",
        "extra_fields": ["model_version"],
    },
}


def make_evidence(source_type, source, status, result, error=None, **extra):
    """构造可追溯证据。status 仅 ok/unavailable/error；按类补充扩展字段。"""
    if source_type not in SOURCE_TYPES:
        raise ValueError("未知 source_type：%s（可选 %s）" % (source_type, SOURCE_TYPES))
    if status not in ALLOWED_STATUS:
        raise ValueError("非法 status：%s（仅允许 %s）" % (status, ALLOWED_STATUS))
    ev = {
        "source_type": source_type,
        "source": source,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "result": result,
        "error": error,
    }
    ev.update(extra)
    return ev


def role_of(evidence):
    """返回证据的作用边界说明（四类证据不可互相替代）。"""
    info = ROLE_BOUNDARIES.get(evidence.get("source_type"), {})
    return {
        "name": info.get("name", "未知类型"),
        "role": info.get("role", "—"),
        "boundary": info.get("boundary", "—"),
    }


def describe(evidence):
    """回答五问：是什么证据、来源、获取时间、是否有效、内容是什么。"""
    role = role_of(evidence)
    valid = evidence.get("status") == "ok"
    return {
        "what": "%s（%s）" % (role["name"], evidence.get("source_type")),
        "source": evidence.get("source"),
        "time": evidence.get("time"),
        "valid": valid,
        "content": evidence.get("result") if valid else None,
        "error": evidence.get("error") if not valid else None,
    }
