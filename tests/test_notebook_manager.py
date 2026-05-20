"""
NotebookManager 单元测试

覆盖：笔记CRUD · 日记生成 · 关注点 · 任务管理 · 自动记笔记决策 · 错误恢复
"""
import sys
sys.path.insert(0, ".")

import pytest
from unittest.mock import AsyncMock, Mock, patch

from packages.agent.notebook_manager import NotebookManager


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def mock_db():
    db = Mock()
    db.insert_notebook = AsyncMock(return_value=1)
    db.get_notebook_notes = AsyncMock(return_value=[])
    db.get_notebook_today_diary = AsyncMock(return_value=None)
    db.get_notebook_diary_list = AsyncMock(return_value=[])
    db.archive_notebook_entries = AsyncMock(return_value=0)
    db.insert_task = AsyncMock(return_value=1)
    db.get_due_tasks = AsyncMock(return_value=[])
    db.get_pending_tasks = AsyncMock(return_value=[])
    db.complete_task = AsyncMock()
    db.cancel_task = AsyncMock()
    return db


@pytest.fixture
def mock_router():
    router = Mock()
    router.route = AsyncMock(return_value="PASS")
    return router


@pytest.fixture
def nb(mock_db, mock_router):
    return NotebookManager(_db=mock_db, _router=mock_router)


# ═══════════════════════════════════════════════════════════
# 笔记（note）
# ═══════════════════════════════════════════════════════════

class TestNoteOperations:
    @pytest.mark.asyncio
    async def test_add_note_basic(self, nb, mock_db):
        await nb.add_note("盒子说下周三有考试")
        mock_db.insert_notebook.assert_called_once_with("note", "盒子说下周三有考试", tags=None)

    @pytest.mark.asyncio
    async def test_add_note_with_tags(self, nb, mock_db):
        await nb.add_note("重要提醒", tags=["考试", "提醒"])
        mock_db.insert_notebook.assert_called_once_with("note", "重要提醒", tags=["考试", "提醒"])

    @pytest.mark.asyncio
    async def test_get_recent_notes(self, nb, mock_db):
        mock_db.get_notebook_notes.return_value = [
            {"content": "笔记1", "kind": "note"},
            {"content": "笔记2", "kind": "note"},
        ]
        result = await nb.get_recent_notes(limit=5)
        assert len(result) == 2
        mock_db.get_notebook_notes.assert_called_once_with(limit=5)


# ═══════════════════════════════════════════════════════════
# 日记（diary）
# ═══════════════════════════════════════════════════════════
# 关注点（focus）
# ═══════════════════════════════════════════════════════════

class TestFocusOperations:
    @pytest.mark.asyncio
    async def test_add_focus_archives_old(self, nb, mock_db):
        await nb.add_focus("盒子这周要考试")
        mock_db.archive_notebook_entries.assert_called_once_with(0)
        mock_db.insert_notebook.assert_called_once_with("focus", "盒子这周要考试", importance=0.8)

    @pytest.mark.asyncio
    async def test_get_current_focus_has_value(self, nb, mock_db):
        mock_db.get_notebook_notes.return_value = [
            {"content": "考试周", "kind": "focus"},
        ]
        result = await nb.get_current_focus()
        assert result == "考试周"

    @pytest.mark.asyncio
    async def test_get_current_focus_empty(self, nb, mock_db):
        mock_db.get_notebook_notes.return_value = []
        result = await nb.get_current_focus()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_current_focus_db_error(self, nb, mock_db):
        mock_db.get_notebook_notes.side_effect = Exception("DB down")
        result = await nb.get_current_focus()
        assert result is None


# ═══════════════════════════════════════════════════════════
# 任务（task）
# ═══════════════════════════════════════════════════════════

class TestTaskOperations:
    @pytest.mark.asyncio
    async def test_schedule_task(self, nb, mock_db):
        await nb.schedule_task("复习数学", priority=2, due_at=1715900000.0)
        mock_db.insert_task.assert_called_once_with(
            title="复习数学", priority=2, due_at=1715900000.0,
        )

    @pytest.mark.asyncio
    async def test_schedule_task_defaults(self, nb, mock_db):
        await nb.schedule_task("随便看看")
        mock_db.insert_task.assert_called_once_with(
            title="随便看看", priority=0, due_at=0.0,
        )

    @pytest.mark.asyncio
    async def test_get_due_tasks(self, nb, mock_db):
        mock_db.get_due_tasks.return_value = [
            {"title": "考试", "due_at": 1715900000.0},
        ]
        result = await nb.get_due_tasks(window_seconds=3600)
        assert len(result) == 1
        assert result[0]["title"] == "考试"

    @pytest.mark.asyncio
    async def test_get_pending_tasks(self, nb, mock_db):
        mock_db.get_pending_tasks.return_value = [
            {"title": "任务1"}, {"title": "任务2"},
        ]
        result = await nb.get_pending_tasks(limit=10)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_complete_task(self, nb, mock_db):
        await nb.complete_task(42)
        mock_db.complete_task.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_cancel_task(self, nb, mock_db):
        await nb.cancel_task(42)
        mock_db.cancel_task.assert_called_once_with(42)


# ═══════════════════════════════════════════════════════════
# 自动记笔记 ★ 核心
# ═══════════════════════════════════════════════════════════

class TestAutoNoteAfterMessage:
    @pytest.mark.asyncio
    async def test_note_detected(self, nb, mock_router, mock_db):
        mock_router.route.return_value = "NOTE: 盒子下周三有考试"

        await nb.auto_note_after_message("下周三我要考试了", "那人家帮伙伴记下来~")
        mock_db.insert_notebook.assert_called_once_with("note", "盒子下周三有考试", tags=None)

    @pytest.mark.asyncio
    async def test_task_detected(self, nb, mock_router, mock_db):
        mock_router.route.return_value = "TASK: 提醒考试 @ 下周三上午9点"

        await nb.auto_note_after_message("下周考试别忘了", "嗯！人家记住了 ~♪")
        mock_db.insert_task.assert_called_once_with(title="提醒考试", priority=1, due_at=0.0)

    @pytest.mark.asyncio
    async def test_pass_no_action(self, nb, mock_router, mock_db):
        mock_router.route.return_value = "PASS"

        await nb.auto_note_after_message("今天吃了个苹果", "苹果很健康呢 ~♪")

        mock_db.insert_notebook.assert_not_called()
        mock_db.insert_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_truncates_long_messages(self, nb, mock_router):
        """超过 300 字的消息应被截断"""
        long_msg = "啊" * 500
        mock_router.route.return_value = "PASS"

        await nb.auto_note_after_message(long_msg, "嗯嗯")

        call_args = mock_router.route.call_args
        messages = call_args[0][1]
        prompt = messages[0]["content"]
        # 截断后不应包含全部 500 字
        assert long_msg not in prompt

    @pytest.mark.asyncio
    async def test_router_failure_does_not_raise(self, nb, mock_router):
        """router 抛异常 → 静默返回，不中断主流程"""
        mock_router.route.side_effect = Exception("Network error")

        # 不应抛异常
        await nb.auto_note_after_message("hello", "hi")

    @pytest.mark.asyncio
    async def test_note_with_empty_content_skipped(self, nb, mock_router, mock_db):
        """NOTE: 后无内容 → 跳过，不写入空笔记"""
        mock_router.route.return_value = "NOTE: "

        await nb.auto_note_after_message("hello", "hi")
        mock_db.insert_notebook.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_with_empty_title_skipped(self, nb, mock_router, mock_db):
        """TASK: 后无内容 → 跳过"""
        mock_router.route.return_value = "TASK: "

        await nb.auto_note_after_message("hello", "hi")
        mock_db.insert_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_with_at_sign_parsed(self, nb, mock_router, mock_db):
        """TASK 中 @ 后的时间描述应被剥离"""
        mock_router.route.return_value = "TASK: 复习数学 @ 下周三晚上"

        await nb.auto_note_after_message("下周考试", "要好好复习哦")

        mock_db.insert_task.assert_called_once()
        call_args = mock_db.insert_task.call_args
        assert call_args.kwargs["title"] == "复习数学"
        assert call_args.kwargs["priority"] == 1
        assert call_args.kwargs["due_at"] > 0  # 时间解析正确工作，返回真实时间戳

    @pytest.mark.asyncio
    async def test_db_write_failure_does_not_raise(self, nb, mock_router, mock_db):
        """DB 写入失败 → 静默返回"""
        mock_router.route.return_value = "NOTE: 重要事项"
        mock_db.insert_notebook.side_effect = Exception("DB locked")

        # 不应抛异常
        await nb.auto_note_after_message("hello", "hi")
