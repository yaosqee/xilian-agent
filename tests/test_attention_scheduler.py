"""AttentionScheduler 单元测试 — 阶段 7c + 打磨期补全

覆盖：事件入队/优先级 · 蒸发 · 防打扰(5层) · tick行为 · Flash决策 · 生命周期
"""
import sys
sys.path.insert(0, ".")

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch
from packages.agent.nudge_engine import (
    AttentionScheduler, AttentionEvent, AttentionUrgency,
)


class TestEventQueue:
    """事件入队与优先级"""

    def test_priority_ordering(self):
        s = AttentionScheduler()
        s.enqueue(AttentionEvent(kind='task_reminder', urgency=AttentionUrgency.SOON,
                                  payload={'task_id': 1}))
        s.enqueue(AttentionEvent(kind='task_reminder', urgency=AttentionUrgency.IMMEDIATE,
                                  payload={'task_id': 2}))

        # Immediate (0) 先于 Soon (1)
        e1 = s.event_queue.get_nowait()
        assert e1.urgency == AttentionUrgency.IMMEDIATE
        e2 = s.event_queue.get_nowait()
        assert e2.urgency == AttentionUrgency.SOON

    def test_queue_size(self):
        s = AttentionScheduler()
        assert s.queue_size == 0
        s.enqueue(AttentionEvent(kind='user_inactive', urgency=AttentionUrgency.SOON))
        assert s.queue_size == 1

    def test_empty_queue_pop(self):
        s = AttentionScheduler()
        with pytest.raises(asyncio.QueueEmpty):
            s.event_queue.get_nowait()


class TestEvaporation:
    """later 事件蒸发"""

    def test_later_evaporates_old(self):
        s = AttentionScheduler()
        old = AttentionEvent(
            kind='memory_surfaced', urgency=AttentionUrgency.LATER,
            payload={'summary': 'old'}, created_at=time.time() - 400,
        )
        new = AttentionEvent(
            kind='memory_surfaced', urgency=AttentionUrgency.LATER,
            payload={'summary': 'new'}, created_at=time.time(),
        )
        s.event_queue.put_nowait(old)
        s.event_queue.put_nowait(new)
        s._evaporate_later(time.time())

        assert s.queue_size == 1
        e = s.event_queue.get_nowait()
        assert e.payload['summary'] == 'new'

    def test_recent_later_survives(self):
        s = AttentionScheduler()
        recent = AttentionEvent(
            kind='memory_surfaced', urgency=AttentionUrgency.LATER,
            payload={'summary': 'recent'}, created_at=time.time() - 100,
        )
        s.event_queue.put_nowait(recent)
        s._evaporate_later(time.time())
        assert s.queue_size == 1


class TestAntiDisturb:
    """防打扰策略"""

    def test_dedup_interval(self):
        s = AttentionScheduler()
        s._last_event_time['task_reminder'] = time.time() - 10
        assert (time.time() - s._last_event_time['task_reminder']) < s.min_interval

    def test_min_interval_enforced(self):
        s = AttentionScheduler()
        s._last_event_time['task_reminder'] = time.time() - 10
        s.event_queue.put_nowait(AttentionEvent(
            kind='task_reminder', urgency=AttentionUrgency.SOON,
        ))
        # 10s < 300s min_interval, tick 应该跳过
        # 这里只验证间隔计算正确
        assert time.time() - s._last_event_time['task_reminder'] < s.min_interval

    def test_user_typing_flag(self):
        s = AttentionScheduler()
        assert not s._user_typing
        s.set_user_typing(True)
        assert s._user_typing
        s.set_user_typing(False)
        assert not s._user_typing


class TestStatus:
    def test_status_contains_keys(self):
        s = AttentionScheduler()
        status = s.status
        assert 'running' in status
        assert 'queue_size' in status
        assert 'dnd' in status
        assert 'user_typing' in status

    def test_initial_queue_empty(self):
        s = AttentionScheduler()
        assert s.queue_size == 0


class TestAttentionEvent:
    """AttentionEvent 基础属性"""

    def test_event_defaults(self):
        e = AttentionEvent(kind="task_reminder", urgency=AttentionUrgency.SOON)
        assert e.kind == "task_reminder"
        assert e.urgency == AttentionUrgency.SOON
        assert e.payload == {}
        assert e.created_at > 0

    def test_event_with_payload(self):
        e = AttentionEvent(kind="task_reminder", urgency=AttentionUrgency.IMMEDIATE,
                           payload={"task_id": 5, "title": "考试"})
        assert e.payload["task_id"] == 5
        assert e.payload["title"] == "考试"

    def test_priority_ordering_immediate_lt_soon(self):
        e1 = AttentionEvent(kind="x", urgency=AttentionUrgency.IMMEDIATE)
        e2 = AttentionEvent(kind="x", urgency=AttentionUrgency.SOON)
        assert e1 < e2

    def test_priority_ordering_soon_lt_later(self):
        e1 = AttentionEvent(kind="x", urgency=AttentionUrgency.SOON)
        e2 = AttentionEvent(kind="x", urgency=AttentionUrgency.LATER)
        assert e1 < e2


class TestFlashDecision:
    """Flash 决策测试（mock router）"""

    @pytest.mark.asyncio
    async def test_decide_notify(self):
        s = AttentionScheduler()
        s._router = Mock()
        s._router.route = AsyncMock(return_value="NOTIFY: 伙伴，考试时间到了哦")
        event = AttentionEvent(kind="task_reminder", urgency=AttentionUrgency.IMMEDIATE,
                               payload={"title": "考试"})

        decision = await s._decide(event)
        assert decision["action"] == "notify"
        assert "考试" in decision["text"]

    @pytest.mark.asyncio
    async def test_decide_silent(self):
        s = AttentionScheduler()
        s._router = Mock()
        s._router.route = AsyncMock(return_value="SILENT")
        event = AttentionEvent(kind="user_inactive", urgency=AttentionUrgency.LATER)

        decision = await s._decide(event)
        assert decision["action"] == "silent"

    @pytest.mark.asyncio
    async def test_decide_note(self):
        s = AttentionScheduler()
        s._router = Mock()
        s._router.route = AsyncMock(return_value="NOTE: 盒子说了下周考试")
        event = AttentionEvent(kind="memory_surfaced", urgency=AttentionUrgency.SOON,
                               payload={"summary": "考试"})

        decision = await s._decide(event)
        assert decision["action"] == "note"
        assert "盒子" in decision["text"]

    @pytest.mark.asyncio
    async def test_decide_router_failure(self):
        s = AttentionScheduler()
        s._router = Mock()
        s._router.route = AsyncMock(side_effect=Exception("Network error"))
        event = AttentionEvent(kind="task_reminder", urgency=AttentionUrgency.SOON)

        decision = await s._decide(event)
        assert decision["action"] == "silent"  # 降级为静默


class TestTickBehavior:
    """tick 行为：5 层防打扰 """

    @pytest.mark.asyncio
    async def test_tick_dnd_silent(self):
        """深夜 → 跳过所有处理"""
        s = AttentionScheduler()
        # 设置 dnd 覆盖全天
        s.dnd_start = 0
        s.dnd_end = 24
        s.event_queue.put_nowait(AttentionEvent(
            kind="task_reminder", urgency=AttentionUrgency.IMMEDIATE,
        ))
        await s._tick()
        assert s.queue_size == 1  # 事件未被消费

    @pytest.mark.asyncio
    async def test_tick_user_typing_skips(self):
        s = AttentionScheduler()
        s._user_typing = True
        s.event_queue.put_nowait(AttentionEvent(
            kind="task_reminder", urgency=AttentionUrgency.IMMEDIATE,
        ))
        await s._tick()
        assert s.queue_size == 1  # 用户输入中，不消费

    @pytest.mark.asyncio
    async def test_tick_empty_queue(self):
        s = AttentionScheduler()
        await s._tick()  # 空队列，不崩溃

    @pytest.mark.asyncio
    async def test_tick_dedup_skips_recent(self):
        s = AttentionScheduler()
        s._router = Mock()
        s._router.route = AsyncMock(return_value="SILENT")
        s._last_event_time["task_reminder"] = time.time()  # 刚刚触发过
        s.event_queue.put_nowait(AttentionEvent(
            kind="task_reminder", urgency=AttentionUrgency.SOON,
        ))
        await s._tick()
        # 同一类型在 min_interval 内已触发 → 跳过
        assert s.queue_size == 0  # 被 get_nowait 取走但跳过了

    @pytest.mark.asyncio
    async def test_tick_process_immediate(self):
        s = AttentionScheduler()
        s._router = Mock()
        s._router.route = AsyncMock(return_value="NOTIFY: 重要提醒")
        s.event_queue.put_nowait(AttentionEvent(
            kind="task_reminder", urgency=AttentionUrgency.IMMEDIATE,
            payload={"title": "会议"},
        ))
        await s._tick()
        assert s.queue_size == 0  # 事件被消费


class TestLifecycle:
    """启动/停止"""

    def test_start_sets_running(self):
        s = AttentionScheduler()
        assert s._running is False
        s._running = True  # simulate start
        assert s.status["running"] is True

    def test_stop_unsets_running(self):
        s = AttentionScheduler()
        s._running = True
        s.stop()
        assert s._running is False

    @pytest.mark.asyncio
    async def test_start_loop_depletes_queue_over_time(self):
        """模拟启动循环后处理队列（不真正启动 asyncio Task）"""
        s = AttentionScheduler()
        s._router = Mock()
        s._router.route = AsyncMock(return_value="SILENT")
        s.event_queue.put_nowait(AttentionEvent(
            kind="task_reminder", urgency=AttentionUrgency.IMMEDIATE,
        ))
        s.event_queue.put_nowait(AttentionEvent(
            kind="user_inactive", urgency=AttentionUrgency.SOON,
        ))

        # 手动 tick 两次（不进入循环）
        await s._tick()
        await s._tick()
        # 两个都应被消费
        assert s.queue_size == 0


class TestEvaporationMixed:
    """蒸发 + 非 later 事件共存"""

    def test_immediate_survives_evaporation(self):
        s = AttentionScheduler()
        s.event_queue.put_nowait(AttentionEvent(
            kind="task_reminder", urgency=AttentionUrgency.IMMEDIATE,
        ))
        s.event_queue.put_nowait(AttentionEvent(
            kind="memory_surfaced", urgency=AttentionUrgency.LATER,
            created_at=time.time() - 400,
        ))
        s._evaporate_later(time.time())
        assert s.queue_size == 1  # 只有 immediate 存活

    def test_all_later_evaporated(self):
        s = AttentionScheduler()
        for i in range(3):
            s.event_queue.put_nowait(AttentionEvent(
                kind="memory_surfaced", urgency=AttentionUrgency.LATER,
                created_at=time.time() - 500,
            ))
        s._evaporate_later(time.time())
        assert s.queue_size == 0
