"""长期记忆：用户兴趣建模、写入触发、自动捕获、矛盾检测"""

from datetime import datetime, timezone
from sqlalchemy import select, update
from db.database import async_session
from db.models import UserInterest
from .decay import apply_decay, is_dormant
from config import get_settings

settings = get_settings()



#先选未休眠的，再从置信度从高到低，置信度低于阈值也不选。
#且每次筛选之前还要进行衰减
async def get_active_interests() -> list[dict]:
    """获取所有活跃兴趣（未休眠），按置信度降序，用于注入 context"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
#查询语句查
    async with async_session() as session:
        result = await session.execute(
            select(UserInterest)
            .where(UserInterest.is_dormant == False)
            .order_by(UserInterest.confidence.desc())
        )
        interests = result.scalars().all()

    active = []
    for i in interests:
        #1.随时间衰减置信度
        new_conf = apply_decay(i.confidence, i.last_accessed_at, now)
        #时间休眠
        if is_dormant(i.last_accessed_at, settings.interest_dormant_days, now):
            await _mark_dormant(i.id)
            continue
        #
        if new_conf != i.confidence:
            await _update_confidence(i.id, new_conf)
        active.append({
            "topic": i.topic,
            "confidence": round(new_conf, 3),
            "memory_type": i.memory_type,
            "access_count": i.access_count,
        })
    return active


#写记忆
async def write_interest(
    topic: str,
    memory_type: str = "preference",
    confidence: float = 1.0,
) -> None:
    """写入一条记忆。事实型覆盖旧的，偏好型新旧加权平均。"""
    topic = topic.strip().lower()

    async with async_session() as session:
        result = await session.execute(
            select(UserInterest).where(UserInterest.topic == topic)
        )
        existing = result.scalar_one_or_none()
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if existing:
            if memory_type == "factual" and existing.memory_type == "factual":
                existing.confidence = confidence
            else:
                existing.confidence = max(
                    existing.confidence * 0.7 + confidence * 0.3, confidence
                )
            existing.last_accessed_at = now
            existing.access_count += 1
            existing.is_dormant = False
        else:
            interest = UserInterest(
                topic=topic,
                confidence=confidence,
                memory_type=memory_type,
                last_accessed_at=now,
                access_count=1,
            )
            session.add(interest)

        await session.commit()



#每次用户聊内容自动记忆（但置信度很低，若只是简单提提很快就是消失）
async def record_access(topic: str) -> None:
    """记录用户访问了某话题，更新 access_count 和 last_accessed_at"""
    topic = topic.strip().lower()

    async with async_session() as session:
        result = await session.execute(
            select(UserInterest).where(UserInterest.topic == topic)
        )
        existing = result.scalar_one_or_none()
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if existing:
            existing.access_count += 1
            existing.last_accessed_at = now
            existing.is_dormant = False
        else:
            interest = UserInterest(
                topic=topic,
                confidence=0.5,
                memory_type="preference",
                last_accessed_at=now,
                access_count=1,
            )
            session.add(interest)

        await session.commit()




async def check_auto_capture(topic: str) -> bool:
    """
    检查是否达到自动捕获阈值：同一主题访问超过 N 篇 →
    自动升级为事实型记忆，提高置信度。
    """
    topic = topic.strip().lower()

    async with async_session() as session:
        result = await session.execute(
            select(UserInterest).where(UserInterest.topic == topic)
        )
        existing = result.scalar_one_or_none()

        if existing and existing.access_count >= settings.interest_auto_capture_threshold:
            existing.memory_type = "factual"
            existing.confidence = min(existing.confidence + 0.1, 1.0)
            await session.commit()
            return True

    return False


async def _update_confidence(interest_id: str, new_confidence: float) -> None:
    async with async_session() as session:
        await session.execute(
            update(UserInterest)
            .where(UserInterest.id == interest_id)
            .values(confidence=new_confidence)
        )
        await session.commit()


async def _mark_dormant(interest_id: str) -> None:
    async with async_session() as session:
        await session.execute(
            update(UserInterest)
            .where(UserInterest.id == interest_id)
            .values(is_dormant=True)
        )
        await session.commit()
