"""B06 基础特征构造：current / mean / delta 共 8 个骨架特征（透明、可解释）。

特征白名单（FEATURE_NAMES）：
- current（窗口最后一点的值）：temp_current / hum_current / light_current        （3 个）
- mean（窗口 6 点均值）：      temp_mean    / hum_mean    / light_mean           （3 个）
- delta（最后一点 - 第一点）：  temp_delta   / hum_delta                          （2 个）

共 8 个。光照不设 delta：光照由昼夜节律主导（白天数千 lux、夜间个位数），
窗口内 delta 无稳定语义，按骨架定义排除。

禁止混入基础特征的数据（由白名单强制，tests/test_features.py 断言）：
- 原始样本序列（除 current/mean/delta 汇总外的任何原始字段展开）；
- sim_scenario（B02 模拟器元数据，不是标签，也不进特征）；
- label_source（标签元数据，仅审计用）；
- B03 天气数据（外部证据，与模型输入严格分离）。

核心特征含义（可解释）：
- temp_mean / hum_mean：窗口期整体环境水平，直接刻画"这 3 小时偏热/偏干"；
- temp_delta / hum_delta：窗口期变化方向，正值=升温/增湿（如热浪逼近），负值=降温/变干；
- light_current + light_mean 结合 timestamp 的昼夜位置由标签规则解读（夜间高光照=异常）。
"""

FEATURE_NAMES = [
    "temp_current", "hum_current", "light_current",
    "temp_mean", "hum_mean", "light_mean",
    "temp_delta", "hum_delta",
]


def extract_features(input_points):
    """从输入窗口的原始采样点计算 8 个骨架特征。"""
    if len(input_points) < 2:
        raise ValueError("输入窗口至少需要 2 个采样点")
    first, last = input_points[0], input_points[-1]
    temps = [p["temperature"] for p in input_points]
    hums = [p["humidity"] for p in input_points]
    lights = [p["light"] for p in input_points]
    n = len(input_points)
    return {
        "temp_current": last["temperature"],
        "hum_current": last["humidity"],
        "light_current": last["light"],
        "temp_mean": round(sum(temps) / n, 2),
        "hum_mean": round(sum(hums) / n, 2),
        "light_mean": round(sum(lights) / n, 2),
        "temp_delta": round(last["temperature"] - first["temperature"], 2),
        "hum_delta": round(last["humidity"] - first["humidity"], 2),
    }


def feature_vector(feats, names=None):
    """按白名单顺序输出特征向量（模型输入）。"""
    names = names or FEATURE_NAMES
    return [feats[n] for n in names]
