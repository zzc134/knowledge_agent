"""记忆衰减：艾宾浩斯启发式衰减，超过 30 天衰减，超过 90 天休眠"""

from datetime import datetime, timezone
import math



#衰减函数
def apply_decay(
    confidence: float,
    last_accessed: datetime,
    now: datetime | None = None,
) -> float:
    """
    艾宾浩斯启发式衰减：距离上次访问越久，置信度越低。
    每 30 天乘一次 0.9（衰减 10%），最低保留 0.01。
    """
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

    days_since_access = (now - last_accessed).days
    if days_since_access <= 0:
        return confidence

    decay_periods = days_since_access / 30
    decay_factor = math.pow(0.9, decay_periods)
    return max(confidence * decay_factor, 0.01)


def is_dormant(
    last_accessed: datetime,
    dormant_days: int = 90,
    now: datetime | None = None,
) -> bool:
    """判断记忆是否进入休眠状态"""
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - last_accessed).days > dormant_days
