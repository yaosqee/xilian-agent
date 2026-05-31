"""测试 Phase 3 画像驱动检索 — persona_boost、config 生成、dual weights

Phase 3 测试：retrieve_memories 画像加权、build_retrieval_config、
embedding 匹配、降级路径、_calculate_importance dual weights、
_cosine_similarity、AgentContext 缓存。
"""
import os
import sys
sys.path.insert(0, ".")

import asyncio
import json
import math
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from packages.shared.database import DatabaseManager
from packages.shared.vector_store import VectorStore
from packages.agent.memory_manager import (
    MemoryManager,
    PERSONA_BOOST_FACTOR,
    PERSONA_PENALTY_FACTOR,
    TOPIC_EMBED_SIMILARITY_THRESHOLD,
    IMPORTANCE_WEIGHTS_FALLBACK,
    IMPORTANCE_WEIGHTS_WITH_PERSONA,
)
from packages.agent.portrait_manager import PortraitManager


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
    router.embed = AsyncMock(return_value=[0.1] * 1024)  # mock bge-m3 vector
    return router


@pytest.fixture
def vs(tmp_db_path):
    store = VectorStore(db_path=tmp_db_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(store.init())
    yield store
    loop.close()


@pytest.fixture
def memory_mgr(db, vs, mock_router):
    return MemoryManager(db=db, vector_store=vs, model_router=mock_router)


@pytest.fixture
def portrait_mgr(db, mock_router):
    return PortraitManager(db=db, model_router=mock_router)


# ═══════════════════════════════════════════════════════════
# Cosine Similarity
# ═══════════════════════════════════════════════════════════

class TestCosineSimilarity:

    def test_identical_vectors(self, memory_mgr):
        v = [0.5] * 10
        sim = memory_mgr._cosine_similarity(v, v)
        assert abs(sim - 1.0) < 0.001

    def test_orthogonal_vectors(self, memory_mgr):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        sim = memory_mgr._cosine_similarity(a, b)
        assert abs(sim - 0.0) < 0.001

    def test_opposite_vectors(self, memory_mgr):
        a = [1.0, 2.0, 3.0]
        b = [-1.0, -2.0, -3.0]
        sim = memory_mgr._cosine_similarity(a, b)
        assert abs(sim - (-1.0)) < 0.001

    def test_zero_vector(self, memory_mgr):
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        sim = memory_mgr._cosine_similarity(a, b)
        assert sim == 0.0


# ═══════════════════════════════════════════════════════════
# Dual Importance Weights
# ═══════════════════════════════════════════════════════════

class TestDualWeights:

    def test_fallback_no_persona(self, memory_mgr):
        """无 persona_topics → 回退到旧权重"""
        exchanges = [{"content": "测试", "role": "user"}]
        emotion = {"primary_intensity": 0.5}
        score = memory_mgr._calculate_importance(exchanges, emotion, persona_topics=None)
        assert 0.1 <= score <= 1.0

    def test_with_persona_topics(self, memory_mgr):
        """有 persona_topics → 使用新权重"""
        exchanges = [{"content": "我在学日语", "role": "user"}]
        emotion = {"primary_intensity": 0.5}
        score = memory_mgr._calculate_importance(
            exchanges, emotion,
            persona_topics=["日语学习", "项目开发"],
        )
        assert 0.1 <= score <= 1.0

    def test_persona_match_boosts_score(self, memory_mgr):
        """对话与画像关注话题匹配 → 重要性提升"""
        exchanges_no_match = [{"content": "今天天气不错", "role": "user"}]
        exchanges_match = [{"content": "我今天又去上了日语课", "role": "user"}]
        emotion = {"primary_intensity": 0.5}

        score_no = memory_mgr._calculate_importance(
            exchanges_no_match, emotion,
            persona_topics=["日语学习"],
        )
        score_yes = memory_mgr._calculate_importance(
            exchanges_match, emotion,
            persona_topics=["日语学习"],
        )
        assert score_yes >= score_no

    def test_weights_sum_to_one(self):
        """权重表各自求和为 1.0（允许浮点误差）"""
        assert abs(sum(IMPORTANCE_WEIGHTS_FALLBACK.values()) - 1.0) < 0.01
        assert abs(sum(IMPORTANCE_WEIGHTS_WITH_PERSONA.values()) - 1.0) < 0.01


# ═══════════════════════════════════════════════════════════
# build_retrieval_config
# ═══════════════════════════════════════════════════════════

class TestBuildRetrievalConfig:

    @pytest.mark.asyncio
    async def test_empty_when_no_l1(self, portrait_mgr, db):
        """无 L1 画像 → 返回空 dict"""
        config = await portrait_mgr.build_retrieval_config()
        assert config == {}

    @pytest.mark.asyncio
    async def test_extracts_topics_from_l1(self, portrait_mgr, db, mock_router):
        """从 L1 的 active_topics / faded_topics JSON 提取话题 embedding"""
        await db.insert_phase_profile(
            content="伙伴最近在学日语和准备面试。",
            active_topics=json.dumps(["日语学习", "面试准备"]),
            faded_topics=json.dumps(["去年旅行"]),
        )

        config = await portrait_mgr.build_retrieval_config()
        assert "boost_topic_embeddings" in config
        assert "penalty_topic_embeddings" in config
        assert len(config["boost_topic_embeddings"]) == 2
        assert len(config["penalty_topic_embeddings"]) == 1

    @pytest.mark.asyncio
    async def test_empty_topics_no_embeddings(self, portrait_mgr, db):
        """active_topics 为空数组 → 不计算 embedding"""
        await db.insert_phase_profile(
            content="测试",
            active_topics="[]",
            faded_topics="[]",
        )
        config = await portrait_mgr.build_retrieval_config()
        assert config == {}

    @pytest.mark.asyncio
    async def test_embed_failure_graceful(self, portrait_mgr, db, mock_router):
        """embedding 失败不阻塞"""
        await db.insert_phase_profile(
            content="测试",
            active_topics=json.dumps(["日语"]),
            faded_topics="[]",
        )
        mock_router.embed.side_effect = Exception("embed failed")

        config = await portrait_mgr.build_retrieval_config()
        # 不应崩溃 — persona_topics 仍返回（供 encode_memory 使用），
        # 但 embedding 列表为空（检索降级）
        assert config.get("persona_topics") == ["日语"]
        assert "boost_topic_embeddings" not in config
        assert "penalty_topic_embeddings" not in config


# ═══════════════════════════════════════════════════════════
# Persona Boost in retrieve_memories (降级路径)
# ═══════════════════════════════════════════════════════════

class TestPersonaBoostFallback:

    @pytest.mark.asyncio
    async def test_no_persona_boost_passed(self, memory_mgr):
        """persona_boost=None → 不影响现有检索（降级路径）"""
        # 无向量时走 fallback 路径
        memory_mgr._embed_text = AsyncMock(return_value=None)

        results = await memory_mgr.retrieve_memories(
            "测试消息", k=3, persona_boost=None,
        )
        # 不崩溃即可 — fallback 路径正常
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_empty_persona_boost(self, memory_mgr):
        """empty dict → 不影响检索"""
        memory_mgr._embed_text = AsyncMock(return_value=None)

        results = await memory_mgr.retrieve_memories(
            "测试消息", k=3, persona_boost={},
        )
        assert isinstance(results, list)


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

class TestConstants:

    def test_boost_less_than_one(self):
        """BOOST_FACTOR < 1 — 降低 adjusted_score → 提升排名"""
        assert PERSONA_BOOST_FACTOR < 1.0

    def test_penalty_greater_than_one(self):
        """PENALTY_FACTOR > 1 — 提高 adjusted_score → 降低排名"""
        assert PERSONA_PENALTY_FACTOR > 1.0

    def test_threshold_in_range(self):
        """相似度阈值在合理范围"""
        assert 0.0 < TOPIC_EMBED_SIMILARITY_THRESHOLD < 1.0
