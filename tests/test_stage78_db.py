"""Notebook + Audit + Forget 集成测试 — 阶段 7b+8"""

import sys
sys.path.insert(0, ".")
import pytest
import asyncio
import os
import time
from pathlib import Path
from packages.shared.database import DatabaseManager


def _run(coro):
    loop = asyncio.new_event_loop()
    try: return loop.run_until_complete(coro)
    finally: loop.close()


@pytest.fixture
def db():
    db_path = Path("data/test_stage78.db")
    m = DatabaseManager(db_path)
    _run(m.init())
    yield m
    _run(m.close())
    if db_path.exists(): os.remove(db_path)


class TestNotebookCRUD:
    def test_insert_and_get_notes(self, db):
        _run(db.insert_notebook("note", "考试", tags=["提醒"]))
        notes = _run(db.get_notebook_notes(limit=10))
        assert len(notes) == 1 and notes[0]["kind"] == "note"
    def test_insert_diary(self, db):
        _run(db.insert_notebook("diary", "今天 ~♪"))
        d = _run(db.get_notebook_today_diary())
        assert d is not None
    def test_insert_focus(self, db):
        _run(db.insert_notebook("focus", "项目", importance=0.8))
        items = _run(db.get_notebook_notes(kind="focus", limit=5))
        assert len(items) == 1 and items[0]["importance"] == 0.8
    def test_archive_old(self, db):
        _run(db.insert_notebook("note", "old"))
        _run(db.archive_notebook_entries(days=0))
        assert len(_run(db.get_notebook_notes(limit=10))) == 0
    def test_diary_list(self, db):
        _run(db.insert_notebook("diary", "d1"))
        _run(db.insert_notebook("diary", "d2"))
        assert len(_run(db.get_notebook_diary_list())) == 2

class TestTasksCRUD:
    def test_pending(self, db):
        _run(db.insert_task("复习", due_at=time.time()+3600))
        assert len(_run(db.get_pending_tasks())) == 1
    def test_due(self, db):
        _run(db.insert_task("考试", priority=2, due_at=time.time()+600))
        assert len(_run(db.get_due_tasks(window_seconds=1800))) == 1
    def test_not_due(self, db):
        _run(db.insert_task("远期", due_at=time.time()+86400))
        assert len(_run(db.get_due_tasks(window_seconds=1800))) == 0
    def test_complete(self, db):
        tid = _run(db.insert_task("x"))
        _run(db.complete_task(tid))
        assert len(_run(db.get_pending_tasks())) == 0
    def test_cancel(self, db):
        tid = _run(db.insert_task("x"))
        _run(db.cancel_task(tid))
        assert len(_run(db.get_pending_tasks())) == 0

class TestAuditLogs:
    def test_log(self, db):
        _run(db.insert_audit_log("prompt_injection_detected", "test", severity="warning"))
        logs = _run(db.get_audit_logs(limit=10))
        assert logs[0]["event_type"] == "prompt_injection_detected"
        assert logs[0]["severity"] == "warning"
    def test_filter(self, db):
        _run(db.insert_audit_log("config_changed", "a"))
        _run(db.insert_audit_log("injection", "b"))
        assert len(_run(db.get_audit_logs(event_type="config_changed"))) == 1
    def test_stats(self, db):
        _run(db.insert_audit_log("config_changed", "a"))
        _run(db.insert_audit_log("config_changed", "b"))
        _run(db.insert_audit_log("tool_executed", "c"))
        s = _run(db.get_audit_stats())
        assert s["total"] == 3 and s["by_type"]["config_changed"] == 2

class TestForgetUserData:
    def test_cascade(self, db):
        _run(db.insert_log("e1", "hi", "hi"))
        _run(db.insert_notebook("note", "n"))
        _run(db.insert_task("t"))
        _run(db.insert_audit_log("x", "x"))
        result = _run(db.forget_user_data())
        assert "conversation_logs" in result["deleted"]
        assert len(_run(db.get_recent(5))) == 0
        assert len(_run(db.get_notebook_notes(limit=5))) == 0
