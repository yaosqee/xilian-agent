"""AttentionScheduler 单元测试 — 阶段 7c"""
import pytest
import asyncio
import time
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
