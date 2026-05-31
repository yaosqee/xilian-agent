"""测试 Phase 2 分层画像 — CRUD、迁移、兼容读取、L1/L0 粗粒化

Phase 2 测试：core_profile / phase_profile CRUD、数据迁移、
兼容读取、CoarseGrainEngine L1/L0 生成、stable_traits 持久化。
"""
import os
import sys
sys.path.insert(0, ".")

import asyncio
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.shared.database import DatabaseManager
from packages.agent.coarse_grain_engine import (
    CoarseGrainEngine,
    L1_TRIGGER_COUNT,
    L0_TRIGGER_VERSIONS,
)


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
    router = MagicMock()
    router.route = AsyncMock()
    return router


@pytest.fixture
def engine(db, mock_router):
    return CoarseGrainEngine(_db=db, _router=mock_router)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

async def _seed_l2_summaries(db, count: int):
    """播种 L2 会话摘要（长度 >= 20 以满足验证）"""
    for i in range(count):
        await db.insert_session_summary(
            content=f"这是第{i+1}条L2会话摘要内容充实字数足够通过最低验证标准",
            source_event_ids=f"{i*5+1},{i*5+2}",
        )


async def _seed_phase_profiles(db, count: int):
    """播种 L1 阶段画像"""
    for i in range(count):
        await db.insert_phase_profile(
            content=f"阶段画像 v{i+1}：伙伴最近在忙项目，"
                    f"性格似乎偏内向但工作很认真。喜欢安静的环境。",
            version=i + 1,
            active_topics='["项目", "技术"]',
            faded_topics='[]',
            change_log=f"第{i+1}版阶段画像",
        )


# ═══════════════════════════════════════════════════════════
# DB 层测试
# ═══════════════════════════════════════════════════════════

class TestCoreProfileCRUD:

    @pytest.mark.asyncio
    async def test_insert_and_get(self, db):
        """core_profile 写入和读取"""
        cid = await db.insert_core_profile(
            content="伙伴是一个内向但细腻的程序员。",
            version=1,
            stable_traits="内向；细腻；喜欢编程",
            change_log="初始版本",
        )
        assert cid > 0

        latest = await db.get_latest_core_profile()
        assert latest is not None
        assert "内向但细腻" in latest["content"]
        assert latest["stable_traits"] == "内向；细腻；喜欢编程"
        assert latest["version"] == 1

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, db):
        """无数据时返回 None"""
        latest = await db.get_latest_core_profile()
        assert latest is None

    @pytest.mark.asyncio
    async def test_version_history(self, db):
        """版本历史查询"""
        await db.insert_core_profile("v1", version=1, change_log="first")
        await db.insert_core_profile("v2", version=2, change_log="second")

        history = await db.get_core_profile_history(limit=5)
        assert len(history) == 2
        assert history[0]["version"] == 2  # 最新排最前

    @pytest.mark.asyncio
    async def test_source_l1_ids_tracking(self, db):
        """source_l1_ids 正确追踪"""
        await db.insert_core_profile(
            content="test",
            source_l1_ids="10,20,30",
        )
        latest = await db.get_latest_core_profile()
        assert latest["source_l1_ids"] == "10,20,30"


class TestPhaseProfileCRUD:

    @pytest.mark.asyncio
    async def test_insert_and_get(self, db):
        """phase_profile 写入和读取"""
        pid = await db.insert_phase_profile(
            content="伙伴最近在学日语，每周上两次课。",
            version=1,
            active_topics='["日语学习"]',
            faded_topics='[]',
            change_log="首次生成",
        )
        assert pid > 0

        latest = await db.get_latest_phase_profile()
        assert latest is not None
        assert "日语" in latest["content"]
        assert "日语学习" in latest["active_topics"]

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, db):
        """无数据时返回 None"""
        latest = await db.get_latest_phase_profile()
        assert latest is None

    @pytest.mark.asyncio
    async def test_history(self, db):
        """版本历史查询"""
        await _seed_phase_profiles(db, 5)
        history = await db.get_phase_profile_history(limit=10)
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_active_topics_json(self, db):
        """active_topics / faded_topics JSON 正确存储"""
        await db.insert_phase_profile(
            content="test",
            active_topics='["学日语", "准备面试"]',
            faded_topics='["去年旅行"]',
        )
        latest = await db.get_latest_phase_profile()
        assert "学日语" in latest["active_topics"]
        assert "去年旅行" in latest["faded_topics"]


class TestDataMigration:

    @pytest.mark.asyncio
    async def test_migrate_from_user_portrait(self, db):
        """从旧 user_portrait 迁移到 core_profile"""
        # 写入旧表
        await db.insert_portrait(
            content="旧版画像：伙伴是程序员。",
            version=3,
            change_log="旧版",
        )

        # 执行迁移
        migrated = await db.migrate_portrait_to_layered()
        assert migrated is True

        # 验证新表
        l0 = await db.get_latest_core_profile()
        assert l0 is not None
        assert "程序员" in l0["content"]
        assert l0["version"] == 1  # 新表从头开始
        assert "从旧版画像迁移" in l0["change_log"]

    @pytest.mark.asyncio
    async def test_no_double_migration(self, db):
        """已迁移时不重复执行"""
        await db.insert_portrait(content="旧画像", version=1)

        first = await db.migrate_portrait_to_layered()
        assert first is True

        second = await db.migrate_portrait_to_layered()
        assert second is False  # 已迁移，跳过

    @pytest.mark.asyncio
    async def test_migrate_empty(self, db):
        """无旧数据时迁移返回 False"""
        migrated = await db.migrate_portrait_to_layered()
        assert migrated is False


class TestCompatibleReading:

    @pytest.mark.asyncio
    async def test_priority_core_profile(self, db):
        """兼容读取优先 core_profile"""
        await db.insert_core_profile(content="新画像 L0", version=1)
        await db.insert_portrait(content="旧画像", version=3)

        latest = await db.get_latest_portrait()
        assert "新画像 L0" in latest["content"]

    @pytest.mark.asyncio
    async def test_fallback_to_user_portrait(self, db):
        """无 core_profile 时回退 user_portrait"""
        await db.insert_portrait(content="旧画像", version=2)

        latest = await db.get_latest_portrait()
        assert latest is not None
        assert "旧画像" in latest["content"]

    @pytest.mark.asyncio
    async def test_none_when_both_empty(self, db):
        """双表都空时返回 None"""
        latest = await db.get_latest_portrait()
        assert latest is None


# ═══════════════════════════════════════════════════════════
# CoarseGrainEngine L1/L0 测试
# ═══════════════════════════════════════════════════════════

class TestL1CoarseGrain:

    @pytest.mark.asyncio
    async def test_should_trigger_l1(self, engine, db):
        """L2 摘要足够 → 触发 L1"""
        await _seed_l2_summaries(db, L1_TRIGGER_COUNT)

        should, reason = await engine._should_trigger_l1()
        assert should is True

    @pytest.mark.asyncio
    async def test_should_not_trigger_l1_insufficient(self, engine, db):
        """L2 摘要不足 → 不触发"""
        await _seed_l2_summaries(db, L1_TRIGGER_COUNT - 1)

        should, reason = await engine._should_trigger_l1()
        assert should is False

    @pytest.mark.asyncio
    async def test_generate_l1(self, engine, mock_router, db):
        """正常生成 L1 阶段画像"""
        await _seed_l2_summaries(db, L1_TRIGGER_COUNT + 2)

        mock_response = MagicMock()
        mock_response.content = (
            '{"portrait": "伙伴最近在忙几个项目，似乎对技术细节很认真。'
            '性格偏内向但细腻，喜欢安静的工作环境。'
            '这些是人家最近慢慢感受到的关于伙伴的事情。",'
            '"changes": "首次生成阶段画像",'
            '"active_topics": ["项目开发", "技术学习"],'
            '"faded_topics": []}'
        )
        mock_router.route.return_value = mock_response

        l1_id = await engine._coarse_to_l1()
        assert l1_id is not None
        assert l1_id > 0

        # 验证写入
        latest = await db.get_latest_phase_profile()
        assert latest is not None
        assert "内向" in latest["content"]
        assert "项目开发" in latest["active_topics"]

    @pytest.mark.asyncio
    async def test_l1_insufficient_summaries(self, engine, db):
        """L2 不足时不生成 L1"""
        await _seed_l2_summaries(db, 1)

        l1_id = await engine._coarse_to_l1()
        assert l1_id is None

    @pytest.mark.asyncio
    async def test_l1_llm_error(self, engine, mock_router, db):
        """LLM 失败时不崩溃"""
        await _seed_l2_summaries(db, L1_TRIGGER_COUNT + 1)
        mock_router.route.side_effect = Exception("API error")

        l1_id = await engine._coarse_to_l1()
        assert l1_id is None


class TestL0CoarseGrain:

    @pytest.mark.asyncio
    async def test_should_trigger_l0(self, engine, db):
        """L1 版本足够 → 触发 L0"""
        await _seed_phase_profiles(db, L0_TRIGGER_VERSIONS)

        should, reason = await engine._should_trigger_l0()
        assert should is True

    @pytest.mark.asyncio
    async def test_should_not_trigger_l0_insufficient(self, engine, db):
        """L1 版本不足 → 不触发"""
        await _seed_phase_profiles(db, L0_TRIGGER_VERSIONS - 1)

        should, reason = await engine._should_trigger_l0()
        assert should is False

    @pytest.mark.asyncio
    async def test_generate_l0(self, engine, mock_router, db):
        """正常生成 L0 核心画像"""
        await _seed_phase_profiles(db, L0_TRIGGER_VERSIONS + 1)

        mock_response = MagicMock()
        mock_response.content = (
            '{"portrait": "伙伴是一个性格底色偏内向但细腻的人。'
            '他始终对技术保持热情，喜欢安静的环境。'
            '这些跨时间的特征让他在人家心里有了独特的轮廓。",'
            '"changes": "首次生成核心画像",'
            '"stable_traits": "内向细腻；热爱技术；喜欢安静；工作认真"}'
        )
        mock_router.route.return_value = mock_response

        l0_id = await engine._coarse_to_l0()
        assert l0_id is not None
        assert l0_id > 0

        # 验证写入
        latest = await db.get_latest_core_profile()
        assert latest is not None
        assert "内向" in latest["content"]
        assert latest["stable_traits"] is not None
        assert "内向细腻" in latest["stable_traits"]

    @pytest.mark.asyncio
    async def test_l0_insufficient_l1(self, engine, db):
        """L1 不足时不生成 L0"""
        await _seed_phase_profiles(db, 1)

        l0_id = await engine._coarse_to_l0()
        assert l0_id is None

    @pytest.mark.asyncio
    async def test_l0_stable_traits_persist(self, engine, mock_router, db):
        """stable_traits 正确持久化"""
        await _seed_phase_profiles(db, L0_TRIGGER_VERSIONS)

        mock_response = MagicMock()
        # 确保 portrait 字段值 ≥ 50 字符
        pad = "测试填充文字"
        long_portrait = pad * 6  # 6 × 6 = 36 chars + other text
        # Total: "核心画像内容测试" + padding ≈ 50+ chars
        long_portrait = "核心画像内容测试" + long_portrait + "最终确保通过验证标准检查。"
        mock_response.content = (
            '{"portrait": "' + long_portrait + '",'
            '"changes": "test",'
            '"stable_traits": "特征A；特征B；特征C"}'
        )
        mock_router.route.return_value = mock_response

        await engine._coarse_to_l0()

        latest = await db.get_latest_core_profile()
        assert "特征A" in latest["stable_traits"]

    @pytest.mark.asyncio
    async def test_l0_with_previous_stable_traits(self, engine, mock_router, db):
        """L0 生成时传入旧 stable_traits 供 LLM 对照"""
        # 先写入初始 L0
        await db.insert_core_profile(
            content="初始核心画像",
            stable_traits="旧特征X；旧特征Y",
            version=1,
        )

        # 播种足够的 L1
        await _seed_phase_profiles(db, L0_TRIGGER_VERSIONS)

        mock_response = MagicMock()
        mock_response.content = (
            '{"portrait": "更新后的核心画像内容字数足够通过验证标准检查。",'
            '"changes": "更新",'
            '"stable_traits": "旧特征X；新特征Z"}'
        )
        mock_router.route.return_value = mock_response

        await engine._coarse_to_l0()

        # 验证 prompt 包含旧 stable_traits
        call_args = mock_router.route.call_args
        prompt_text = str(call_args[0][1][0]["content"])
        assert "旧特征X" in prompt_text
        assert "旧特征Y" in prompt_text


class TestForceCoarseAllCascade:

    @pytest.mark.asyncio
    async def test_full_cascade_l2_to_l0(self, engine, mock_router, db):
        """force_coarse_all 完整级联 L2→L1→L0"""
        # 播种微事件
        for i in range(15):
            await db.insert_micro_event(f"事件{i}", "fact", 0.8)

        # 播种 L2 摘要（模拟历史积累）
        await _seed_l2_summaries(db, L1_TRIGGER_COUNT)
        await _seed_phase_profiles(db, L0_TRIGGER_VERSIONS)

        # L2 mock
        mock_l2 = MagicMock()
        mock_l2.content = '{"summary": "L2摘要内容充实字数足够通过最低验证标准检查要求", "topics": ["测试"]}'

        # L1 mock（≥50 字）
        mock_l1 = MagicMock()
        mock_l1.content = (
            '{"portrait": "这是一个L1阶段画像测试内容包含了足够多的中文字符'
            '以确保能够通过最低五十字符的验证标准检查要求测试。",'
            '"changes": "test",'
            '"active_topics": ["测试"],'
            '"faded_topics": []}'
        )

        # L0 mock（≥50 字）
        mock_l0 = MagicMock()
        mock_l0.content = (
            '{"portrait": "这是一个L0核心画像测试内容包含了足够多的中文字符'
            '以确保能够通过最低五十字符的验证标准检查要求测试验证。",'
            '"changes": "test",'
            '"stable_traits": "测试特征"}'
        )

        # 三次 LLM 调用分别返回
        mock_router.route.side_effect = [mock_l2, mock_l1, mock_l0]

        result = await engine.force_coarse_all()

        # 应返回 L0 内容
        assert result is not None
        assert "L0" in result or "核心" in result


# ═══════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════

class TestCheckAndCoarseFull:

    @pytest.mark.asyncio
    async def test_l2_only(self, engine, mock_router, db):
        """仅有 L2 触发条件时只生成 L2"""
        for i in range(15):
            await db.insert_micro_event(f"事件{i}", "fact", 0.8)

        mock_response = MagicMock()
        mock_response.content = '{"summary": "L2摘要内容充实字数足够通过最低验证标准检查要求", "topics": ["测试"]}'
        mock_router.route.return_value = mock_response

        result = await engine.check_and_coarse()
        assert result is not None
        assert result["l2_updated"] is True
        assert result.get("l1_updated") is False
        assert result.get("l0_updated") is False

    @pytest.mark.asyncio
    async def test_noop(self, engine, db):
        """无触发条件时 check_and_coarse 返回 None"""
        result = await engine.check_and_coarse()
        assert result is None
