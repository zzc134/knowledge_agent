"""
记忆系统评估：兴趣模型准确率、衰减合理性
"""
import sys
sys.path.insert(0, ".")

import asyncio
from datetime import datetime, timezone
from memory.long_term import get_active_interests, write_interest, record_access, check_auto_capture
from memory.decay import apply_decay, is_dormant


async def test_decay_curve():
    """测试衰减曲线是否符合预期"""
    print("--- 衰减曲线测试 ---")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    base_conf = 1.0

    test_points = [0, 15, 30, 60, 90, 120, 365]
    for days in test_points:
        last_accessed = datetime(
            now.year, now.month, now.day
        ).replace(tzinfo=None)
        from datetime import timedelta
        last_accessed = now - timedelta(days=days)
        new_conf = apply_decay(base_conf, last_accessed, now)
        dormant = is_dormant(last_accessed, dormant_days=90, now=now)
        print(f"  {days:>4}天前 → 置信度: {new_conf:.4f} {'[休眠]' if dormant else ''}")


async def test_auto_capture():
    """测试自动捕获阈值"""
    print("\n--- 自动捕获测试 ---")
    topic = "test_auto_capture_topic"

    for i in range(7):
        await record_access(topic)
        captured = await check_auto_capture(topic)
        print(f"  访问 {i+1} 次 → 自动捕获: {'是' if captured else '否'}")

    interests = await get_active_interests()
    test_interest = next((i for i in interests if i['topic'] == topic), None)
    if test_interest:
        print(f"  最终: memory_type={test_interest['memory_type']}, confidence={test_interest['confidence']}")


async def test_write_interest():
    """测试记忆写入和更新"""
    print("\n--- 记忆写入测试 ---")

    await write_interest("ai_agent", memory_type="factual", confidence=0.9)
    print("  写入事实型记忆: ai_agent (0.9)")

    await write_interest("ai_agent", memory_type="factual", confidence=1.0)
    print("  再次写入事实型: ai_agent (1.0) → 应覆盖")

    await write_interest("prompt_engineering", memory_type="preference", confidence=0.6)
    print("  写入偏好型记忆: prompt_engineering (0.6)")

    await write_interest("prompt_engineering", memory_type="preference", confidence=0.8)
    print("  再次写入偏好型: prompt_engineering (0.8) → 应加权平均")

    interests = await get_active_interests()
    for i in interests[:5]:
        print(f"  [{i['memory_type']}] {i['topic']}: {i['confidence']:.3f} ({i['access_count']}次访问)")


async def main():
    print("记忆系统评估")
    print("=" * 50)

    await test_decay_curve()
    await test_auto_capture()
    await test_write_interest()

    print("\n" + "=" * 50)
    print("活跃兴趣列表:")
    interests = await get_active_interests()
    for i in interests:
        print(f"  [{i['memory_type']}] {i['topic']}: {i['confidence']:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
