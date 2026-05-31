"""端到端画像管线集成测试

模拟多轮对话 → 验证完整管线：
  微事件提取 → L2→L1→L0 粗粒化 → 检索加权 → 上下文注入 → 笔记联动 → 月度重建

所有 LLM 调用均 mock，无需 API Key。
"""
import os
import sys
sys.path.insert(0, ".")

import asyncio
import json
import tempfile
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.shared.database import DatabaseManager
from packages.shared.vector_store import VectorStore
from packages.agent.memory_manager import MemoryManager
from packages.agent.portrait_manager import PortraitManager
from packages.agent.notebook_manager import NotebookManager
from packages.agent.agent_context import AgentContext
from packages.agent.context_builder import (
    ContextBuilder,
    DatetimeModule, PortraitModule, PortraitGuidanceModule,
    EmotionModule, MemoryModule, NotebookModule, NotebookTaskModule,
    AffectionModule,
)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _make_response(content):
    """创建 mock LLM 响应。"""
    m = MagicMock()
    m.content = content
    return m


def _event_json(events):
    return json.dumps({"events": events})


def _events_fact(i):
    return [{"content": f"事实事件内容{i}", "category": "fact", "confidence": 0.9}]


# 所有 mock 文本需 >= 对应门控（L2 >= 20, L1/L0/legacy >= 50）
PAD = "额外填充文字"
L2_SUMMARY = "L2摘要" + PAD * 4 + "通过验证标准检查。"
L1_PORTRAIT = "L1阶段画像" + PAD * 8 + "达到最低五十字符验证标准检查要求测试。"
L0_PORTRAIT = "L0核心画像" + PAD * 8 + "达到最低五十字符验证标准检查要求测试验证。"
LEGACY_PORTRAIT = "旧式重写画像" + PAD * 8 + "达到最低五十字符验证标准检查要求测试确保通过。"


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
        os.unlink(path + "-wal")
        os.unlink(path + "-shm")
    except FileNotFoundError:
        pass


@pytest.fixture
def db(tmp_db_path):
    loop = asyncio.new_event_loop()
    db = DatabaseManager(tmp_db_path)
    loop.run_until_complete(db.init())
    yield db
    loop.run_until_complete(db.close())
    loop.close()


@pytest.fixture
def mock_router():
    """Mock ModelRouter — 不设默认 side_effect，由测试自行控制。"""
    router = MagicMock()
    router.route = AsyncMock()
    router.embed = AsyncMock(return_value=[0.1] * 1024)
    return router


@pytest.fixture
def vs(tmp_db_path):
    store = VectorStore(db_path=tmp_db_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(store.init())
    yield store
    loop.close()


# ═══════════════════════════════════════════════════════════
# 模拟对话助手
# ═══════════════════════════════════════════════════════════

class SimulatedConversation:
    """模拟多轮对话，驱动完整画像管线。"""

    def __init__(self, db, mock_router, vs_store=None):
        self.db = db
        self.router = mock_router
        self.vs = vs_store

        self.memory_mgr = MemoryManager(
            db=db, vector_store=vs_store, model_router=mock_router,
        ) if vs_store else None
        self.portrait_mgr = PortraitManager(db=db, model_router=mock_router)
        self.notebook_mgr = NotebookManager(_db=db, _router=mock_router)

        self.ctx = AgentContext()
        self.ctx._router = mock_router

        self.builder = ContextBuilder(total_budget=800)
        self.builder.register(DatetimeModule())
        self.builder.register(PortraitGuidanceModule(self.ctx))
        self.builder.register(PortraitModule(self.ctx))
        self.builder.register(EmotionModule(self.ctx))
        self.builder.register(MemoryModule(self.ctx))
        nb_module = NotebookModule()
        nb_module.set_notebook(self.notebook_mgr)
        self.builder.register(nb_module)
        self.builder.register(AffectionModule())
        task_module = NotebookTaskModule()
        task_module.set_notebook(self.notebook_mgr)
        self.builder.register(task_module)

        self.round = 0

    async def send(self, user_msg: str, assistant_reply: str = ""):
        """模拟一轮对话。"""
        self.round += 1
        self.ctx._last_user_message = user_msg
        if not assistant_reply:
            assistant_reply = f"回复第{self.round}轮"

        await self.portrait_mgr.extract_then_check_coarse(user_msg, assistant_reply)

        if self.memory_mgr:
            cached = getattr(self.ctx, '_persona_boost_config', None)
            if cached is None:
                cached = await self.portrait_mgr.build_retrieval_config()
                self.ctx._persona_boost_config = cached
            results = await self.memory_mgr.retrieve_memories(
                user_msg, k=3, persona_boost=cached,
            )
            self.ctx.memory_retrieval = results

        portrait_ctx = ""
        if self.ctx.core_profile:
            portrait_ctx = f"伙伴性格：{self.ctx.core_profile[:100]}"
        await self.notebook_mgr.auto_note_after_message(
            user_msg, assistant_reply, portrait_context=portrait_ctx,
        )

        ctx_notes = await self.builder.build()
        self.ctx.add_message("user", user_msg)
        self.ctx.add_message("assistant", assistant_reply)
        return ctx_notes

    async def reload_portraits(self):
        l0 = await self.db.get_latest_core_profile()
        if l0 and l0.get("content"):
            self.ctx.core_profile = l0["content"]
            self.ctx._current_l0_version = l0.get("version", 1)
        l1 = await self.db.get_latest_phase_profile()
        if l1 and l1.get("content"):
            self.ctx.phase_profile = l1["content"]
            self.ctx._current_l1_version = l1.get("version", 1)


# ═══════════════════════════════════════════════════════════
# 端到端测试
# ═══════════════════════════════════════════════════════════

class TestEndToEndPipeline:

    @pytest.mark.asyncio
    async def test_micro_events_accumulate(self, db, mock_router):
        """10 轮对话 → 微事件正确累积。"""
        sim = SimulatedConversation(db, mock_router)

        for i in range(10):
            events = _events_fact(i)
            mock_router.route.return_value = _make_response(_event_json(events))
            await sim.send(f"测试消息{i}", f"回复{i}")

        active = await db.get_active_micro_events(limit=50)
        assert len(active) == 10

    @pytest.mark.asyncio
    async def test_l2_triggered_after_threshold(self, db, mock_router):
        """累积 ≥10 条事件 → L2 触发。"""
        sim = SimulatedConversation(db, mock_router)

        # 播种 10 条事件
        for i in range(10):
            events = _events_fact(i)
            mock_router.route.return_value = _make_response(_event_json(events))
            await sim.send(f"消息{i}", f"回复{i}")

        # 第 11 条：extract 返回事件 + check_and_coarse 触发 L2
        # extract_then_check_coarse 内部两次调用 route：先 extract，后 coarse
        mock_router.route.side_effect = [
            _make_response(_event_json(_events_fact(11))),     # extract
            _make_response(json.dumps({                        # L2 coarse
                "summary": L2_SUMMARY,
                "topics": ["测试"],
            })),
        ]
        await sim.send("触发阈值", "回复")

        summaries = await db.get_recent_session_summaries(limit=5)
        assert len(summaries) > 0

        # 事件已被消费
        active_after = await db.get_active_micro_events(limit=50)
        assert len(active_after) < 11

    @pytest.mark.asyncio
    async def test_l1_triggered_with_enough_l2(self, db, mock_router):
        """L2 积累 ≥3 条 → L1 触发。"""
        sim = SimulatedConversation(db, mock_router)

        for i in range(3):
            await db.insert_session_summary(
                content=L2_SUMMARY,
                source_event_ids=f"{i*5+1}",
            )

        # 触发 check_and_coarse → 应触发 L1
        mock_router.route.return_value = _make_response(json.dumps({
            "portrait": L1_PORTRAIT,
            "changes": "首次L1",
            "active_topics": ["测试"],
            "faded_topics": [],
        }))

        engine = sim.portrait_mgr._coarse_engine
        await engine.check_and_coarse()

        l1 = await db.get_latest_phase_profile()
        assert l1 is not None
        assert "测试" in l1.get("active_topics", "")

    @pytest.mark.asyncio
    async def test_l0_triggered_with_enough_l1(self, db, mock_router):
        """L1 积累 ≥3 版本 → L0 触发。"""
        sim = SimulatedConversation(db, mock_router)

        for i in range(3):
            await db.insert_phase_profile(
                content=L1_PORTRAIT,
                version=i + 1,
                active_topics='["测试"]',
                faded_topics="[]",
            )

        mock_router.route.return_value = _make_response(json.dumps({
            "portrait": L0_PORTRAIT,
            "changes": "首次L0",
            "stable_traits": "特征A；特征B",
        }))

        engine = sim.portrait_mgr._coarse_engine
        await engine._coarse_to_l0()

        l0 = await db.get_latest_core_profile()
        assert l0 is not None
        assert "特征A" in l0.get("stable_traits", "")

    @pytest.mark.asyncio
    async def test_retrieval_config_from_l1(self, db, mock_router):
        """有 L1 画像时 build_retrieval_config 返回有效配置。"""
        await db.insert_phase_profile(
            content=L1_PORTRAIT,
            active_topics=json.dumps(["日语学习", "面试准备"]),
            faded_topics=json.dumps(["去年旅行"]),
        )

        pm = PortraitManager(db=db, model_router=mock_router)
        config = await pm.build_retrieval_config()

        assert "persona_topics" in config
        assert "日语学习" in config["persona_topics"]
        assert len(config.get("boost_topic_embeddings", [])) == 2

    @pytest.mark.asyncio
    async def test_context_injection_layered_portrait(self, db, mock_router):
        """上下文注入包含分层画像。"""
        sim = SimulatedConversation(db, mock_router)

        await db.insert_core_profile(content=L0_PORTRAIT, version=1)
        await db.insert_phase_profile(content=L1_PORTRAIT, version=1,
                                       active_topics='["日语学习"]')
        await sim.reload_portraits()

        # 首条消息 → 完整 L1+L0
        mock_router.route.return_value = _make_response(_event_json([]))
        ctx_notes = await sim.send("你好呀")
        assert "最近的那一页" in ctx_notes or "最深的那几笔记" in ctx_notes

        # 第二条 → 不应崩溃
        ctx_notes2 = await sim.send("今天天气不错")
        assert isinstance(ctx_notes2, str)

    @pytest.mark.asyncio
    async def test_notebook_with_portrait_context(self, db, mock_router):
        """自动笔记使用画像上下文。"""
        sim = SimulatedConversation(db, mock_router)

        await db.insert_phase_profile(content=L1_PORTRAIT, version=1,
                                       active_topics='["日语学习"]')
        await sim.reload_portraits()

        mock_router.route.side_effect = [
            _make_response(_event_json([])),         # extract
            _make_response("NOTE: 伙伴提到日语课"),   # auto_note
        ]

        await sim.send("今天日语课学了新单词", "加油呀 ~♪")

        notes = await db.get_notebook_notes(limit=5)
        assert len(notes) > 0

    @pytest.mark.asyncio
    async def test_icebreaker_accumulates_events(self, db, mock_router):
        """破冰对话 → 微事件累积。"""
        sim = SimulatedConversation(db, mock_router)
        sim.ctx.icebreaker_active = True

        for i in range(6):
            events = _events_fact(i)
            mock_router.route.return_value = _make_response(_event_json(events))
            await sim.send(f"我叫盒子喜欢编程{i}", f"原来伙伴喜欢编程呀~")

        active = await db.get_active_micro_events(limit=20)
        assert len(active) == 6

    @pytest.mark.asyncio
    async def test_monthly_rebuild_ok_when_similar(self, db, mock_router):
        """月度重建：内容相似 → 不迁移。"""
        await db.insert_core_profile(content=L0_PORTRAIT, version=1)

        # 播种 episodic 记忆（_legacy_consolidate 需要）
        await db.insert_episodic_memory(
            summary="伙伴喜欢编程测试记忆内容足够长用于验证旧式重写管线。",
            raw_conversation='[{"role":"user","content":"测试"}]',
            importance=0.5,
        )

        pm = PortraitManager(db=db, model_router=mock_router)
        mock_router.route.return_value = _make_response(json.dumps({
            "portrait": L0_PORTRAIT,
            "changes": "重建",
        }))

        result = await pm.monthly_full_rebuild()
        assert result is not None
        assert result["diff_ratio"] < 0.5
        assert result["migrated"] is False

    @pytest.mark.asyncio
    async def test_monthly_rebuild_divergence_migrates(self, db, mock_router):
        """月度重建：差异大 → 自动迁移。"""
        await db.insert_core_profile(
            content="完全不同的旧L0核心画像描述用于差异检测触发逻辑验证。",
            version=1,
        )

        await db.insert_episodic_memory(
            summary="伙伴喜欢编程测试记忆内容足够长用于验证旧式重写管线。",
            raw_conversation='[{"role":"user","content":"测试"}]',
            importance=0.5,
        )

        pm = PortraitManager(db=db, model_router=mock_router)
        rebuilt = "月度重建" + PAD * 8 + "全新内容完全不同于旧版本用于验证自动迁移逻辑。"
        mock_router.route.return_value = _make_response(json.dumps({
            "portrait": rebuilt,
            "changes": "重建",
        }))

        result = await pm.monthly_full_rebuild()
        assert result is not None
        assert result["migrated"] is True

    @pytest.mark.asyncio
    async def test_text_difference_ratio(self, db):
        """_text_difference_ratio 基本行为。"""
        pm = PortraitManager(db=db, model_router=None)

        assert pm._text_difference_ratio("完全相同", "完全相同") == 0.0
        assert pm._text_difference_ratio("伙伴喜欢编程", "伙伴讨厌早起") > 0.5
        assert pm._text_difference_ratio("", "") == 0.0
        assert pm._text_difference_ratio("有内容", "") == 1.0
