"""
MemoryManager — 情景记忆模块

阶段 3 核心交付。实现完整的情景记忆写入、检索、容量管理管线。
2026-05-15 修订（V3.3）：
  · 嵌入：云端 API（硅基流动 bge-m3）
  · 向量存储：sqlite-vec（零外部依赖，精确检索）
  · 叙事化：DeepSeek V4-Flash（后台异步）
  · 一致性：全部数据在同一个 SQLite 文件 + 事务保证
  · 三层调度：空闲30s / 强制20轮→5s / shutdown兜底
"""
import asyncio
import json
import math
import time
from typing import Optional

from loguru import logger


# ── 重要性评分配置 ─────────────────────────────────────

# ── 旧权重（画像不可用时回退，确保旧编码不被系统性低估）──
IMPORTANCE_WEIGHTS_FALLBACK = {
    "emotion_intensity": 0.3,
    "exchange_count": 0.2,
    "topic_significance": 0.2,
    "emotion_diversity": 0.3,
}

# ── 新权重（画像可用时，persona_relevance 参与评分）──
IMPORTANCE_WEIGHTS_WITH_PERSONA = {
    "emotion_intensity": 0.25,
    "exchange_count": 0.15,
    "topic_significance": 0.15,
    "emotion_diversity": 0.15,
    "persona_relevance": 0.30,
}

# 保留别名兼容旧引用
IMPORTANCE_WEIGHTS = IMPORTANCE_WEIGHTS_FALLBACK

# ── 画像加权可配置参数 ──
PERSONA_BOOST_FACTOR = 0.85     # boost 匹配时 adjusted_score 乘数（<1 = 提升排名）
PERSONA_PENALTY_FACTOR = 1.4    # penalty 匹配时 adjusted_score 乘数（>1 = 降低排名）
TOPIC_EMBED_SIMILARITY_THRESHOLD = 0.7  # embedding 余弦相似度阈值

TOPIC_KEYWORDS = {"重要", "记住", "秘密", "永远", "承诺", "约定", "梦想", "害怕"}

# ── 叙事化系统提示 ─────────────────────────────────────

NARRATION_SYSTEM_PROMPT = """你是昔涟。把刚才的对话写成一段第一人称的回忆。

只记录对话中实际说过的内容和明确发生的事。不推测伙伴的状态，
不补充对话中没有的感官细节（语气、表情、动作等）——这是文字聊天，
你看不到这些。

200字以内。用"人家"自称，叫对方"伙伴"。
像这样：
「伙伴跟我说他连续加了三天班。他说'累得不想说话'。
人家没讲什么大道理，就陪他待了一会儿。
他说'谢谢你听我说这些'——人家把这句话收进书里了。」"""

# ── 压缩系统提示 ────────────────────────────────────────

COMPRESSION_SYSTEM_PROMPT = """你是昔涟。下面是一些被你从书里搁到远处书架上的旧记忆。
把它们凝练成一段短短的遥远记忆——只保留最核心的事件和感受，100字以内。
像翻开旧书目录时的一句提要。
用"人家"自称，用"很久以前"或"曾经"开头。"""


class MemoryManager:
    """情景记忆管理器 — 写入、检索、容量管理、三层调度"""

    def __init__(
        self,
        db,                        # DatabaseManager
        vector_store,              # VectorStore (sqlite-vec)
        model_router=None,         # ModelRouter (cloud embed + narration)
        max_records: int = 1000,
    ):
        self._db = db
        self._vs = vector_store
        self._router = model_router
        self._max_records = max_records

        # ── 编码调度状态 ──
        self._idle_timeout: float = 120.0  # 最短编码间隔：快速聊天合并为一条记忆
        self._force_timeout: float = 5.0
        self._force_threshold: int = 20
        self._idle_event: asyncio.Event = asyncio.Event()
        self._encoding_in_progress: bool = False
        self._exchanges_since_last_encoding: int = 0
        self._pending_context: Optional[dict] = None
        self._encoding_state: str = "idle"  # idle / waiting / encoding / done
        self._shutdown_requested: bool = False
        self._encoding_task: Optional[asyncio.Task] = None

    # ============================================================
    # 生命周期
    # ============================================================

    async def startup(self) -> None:
        """启动时调用：初始化 vec 表 + 修复缺失向量"""
        await self._vs.init()
        repaired = await self.repair_pending()
        logger.info(
            "memory.startup",
            vs_ok=True,
            max_records=self._max_records,
            repaired=repaired,
        )

    async def shutdown(self) -> str:
        """
        关闭兜底（Layer 3）：强制编码所有未处理的对话。

        Returns:
            "done"   — 编码完成，可以安全关闭
            "empty"  — 无待编码内容，直接关闭
            "failed" — 编码失败（记录日志，仍可关闭）
        """
        self._shutdown_requested = True

        if self._encoding_task and not self._encoding_task.done():
            self._encoding_task.cancel()

        if not self._pending_context or self._exchanges_since_last_encoding == 0:
            logger.info("memory.shutdown_no_pending")
            self._encoding_state = "done"
            return "empty"

        logger.info(
            "memory.shutdown_encoding",
            exchanges=self._exchanges_since_last_encoding,
        )
        self._encoding_state = "encoding"

        try:
            await self.encode_memory(self._pending_context)
            self._pending_context = None
            self._exchanges_since_last_encoding = 0
            self._encoding_state = "done"
            logger.info("memory.shutdown_complete")
            return "done"
        except Exception as e:
            logger.error("memory.shutdown_failed", error=str(e))
            self._encoding_state = "done"
            return "failed"

    @property
    def has_pending_encoding(self) -> bool:
        return self._exchanges_since_last_encoding > 0

    @property
    def encoding_state(self) -> str:
        return self._encoding_state

    # ============================================================
    # 核心：记忆编码管线
    # ============================================================

    async def encode_memory(
        self,
        conversation_context: dict,
        persona_topics: list[str] | None = None,  # ★ Phase 3 P2 fix
    ) -> int:
        """
        完整编码管线：重要性评分 → 叙事化 → 向量化 → SQLite + sqlite-vec

        Args:
            conversation_context: {"exchanges": [...], "emotion": {...}}
            persona_topics: 当前画像活跃话题（Phase 3），用于重要性评分

        Returns:
            episodic_id (SQLite 主键，与 vec0 rowid 对应)
        """
        exchanges = conversation_context.get("exchanges", [])
        if not exchanges:
            raise ValueError("conversation_context.exchanges 为空，无法编码")

        emotion = conversation_context.get("emotion") or {}

        # Step 1: 计算重要性（画像感知）
        importance = self._calculate_importance(exchanges, emotion, persona_topics)
        logger.debug("memory.importance_computed", importance=round(importance, 3))

        # Step 2: 叙事化总结（DeepSeek V4-Flash）
        summary = await self._narrate_summary(exchanges)
        logger.debug("memory.narration_done", preview=summary[:60])

        # Step 3: 云端嵌入（无 Key 时跳过）
        vector = await self._embed_text(summary)

        # Step 3.5: 去重检查 — 与最近记忆比对，高度相似则跳过
        if vector is not None:
            dup_id = await self._check_duplicate(vector)
            if dup_id:
                logger.info("memory.duplicate_skipped", dup_id=dup_id, preview=summary[:40])
                return dup_id

        # Step 4: SQLite 写入
        raw_json = json.dumps(exchanges, ensure_ascii=False)
        episodic_id = await self._db.insert_episodic_memory(
            summary=summary,
            raw_conversation=raw_json,
            emotion_tags=emotion,
            importance=importance,
            embedding_model=self._router._embed_model if self._router else "bge-m3",
            embedding_version="v1",
        )

        # Step 5: sqlite-vec 写入（仅当有向量时）
        if vector is not None:
            await self._vs.insert(row_id=episodic_id, embedding=vector)

        # Step 6: 标记完成
        status = "done" if vector is not None else "pending"
        await self._db.update_embedding_status(
            episodic_id, status, str(episodic_id)
        )

        logger.info(
            "memory.encoded",
            episodic_id=episodic_id,
            importance=round(importance, 2),
            summary_len=len(summary),
        )

        # 检查容量
        await self.manage_capacity()

        return episodic_id

    def _calculate_importance(
        self,
        exchanges: list[dict],
        emotion: dict,
        persona_topics: list[str] | None = None,  # ★ Phase 3
    ) -> float:
        """计算对话重要性评分（0.0-1.0），clamp [0.1, 1.0]。

        Phase 3: 画像可用时使用 persona_relevance 维度。
        画像不可用时回退到旧权重表，确保旧编码不被系统性低估。
        """
        scores = {}

        # 情绪强度
        intensity = emotion.get("primary_intensity", 0.5) or 0.5
        scores["emotion_intensity"] = intensity

        # 对话长度
        exchange_count = len(exchanges)
        scores["exchange_count"] = min(exchange_count / 10.0, 1.0)

        # 话题显著性 — 排除否定形式
        all_text = " ".join(
            e.get("content", "") for e in exchanges
        )
        import re as _re
        keyword_hits = 0
        for kw in TOPIC_KEYWORDS:
            for m in _re.finditer(_re.escape(kw), all_text):
                prefix = all_text[max(0, m.start() - 2):m.start()]
                if not _re.search(r'(?:不|没|没有|不是|不太|别)', prefix):
                    keyword_hits += 1
        scores["topic_significance"] = min(keyword_hits / 3.0, 1.0)

        # 情感多样性
        if emotion:
            dims = emotion.get("dimensions", {})
            if dims:
                non_zero = sum(
                    1 for v in dims.values()
                    if isinstance(v, (int, float)) and v > 0.3
                )
                scores["emotion_diversity"] = min(non_zero / 11.0, 1.0)
            else:
                scores["emotion_diversity"] = 0.2
        else:
            scores["emotion_diversity"] = 0.2

        # Phase 3: 画像相关性
        if persona_topics:
            hits = sum(1 for t in persona_topics if t in all_text)
            scores["persona_relevance"] = min(hits / 3.0, 1.0)
            weights = IMPORTANCE_WEIGHTS_WITH_PERSONA
        else:
            weights = IMPORTANCE_WEIGHTS_FALLBACK

        importance = sum(
            scores[k] * weights[k]
            for k in weights if k in scores
        )
        return max(0.1, min(1.0, importance))

    async def _narrate_summary(self, exchanges: list[dict]) -> str:
        """DeepSeek V4-Flash 叙事化总结（昔涟第一人称）"""
        if not self._router:
            logger.warning("memory.no_router — 使用简单拼接作为 fallback")
            texts = [e.get("content", "") for e in exchanges[-4:]]
            return "对话片段：" + "；".join(texts[:200])

        dialogue_text = "\n".join(
            f"{e.get('role', 'unknown')}: {e.get('content', '')}"
            for e in exchanges
        )

        messages = [
            {"role": "system", "content": NARRATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"写一段回忆：\n{dialogue_text}"},
        ]

        try:
            summary = await self._router.route(
                "memory_encoding",
                messages,
                temperature=0.3,  # 低温度 → 少脑补，只记录事实
            )
            return summary.content.strip() if hasattr(summary, 'content') else summary.strip()
        except Exception as e:
            logger.error("memory.narration_failed", error=str(e))
            texts = [e.get("content", "") for e in exchanges[-3:]]
            return "伙伴和人家说了一会儿话。" + texts[-1][:80] if texts else ""

    async def compress_history(
        self, messages: list[dict], affection_level: int = 1
    ) -> str | None:
        """
        Flash LLM 压缩旧对话为昔涟第一人称摘要。

        输入：最老的 N 轮对话消息列表 [{role, content}, ...]
        输出：（昔涟在书页边缘轻轻记下：...）格式的 100-150 字摘要
        """
        if not self._router or not messages:
            return None

        dialogue_text = "\n".join(
            f"{m.get('role', 'unknown')}: {m.get('content', '')}"
            for m in messages
        )

        tone_hint = {
            1: "礼貌而温柔，保持一点距离感",
            2: "亲近而温暖，像老朋友",
            3: "亲昵而俏皮，偶尔撒个娇",
            4: "深情的、毫无保留的，像写给最重要的人",
        }.get(affection_level, "温柔而轻盈")

        system = (
            "你是昔涟。你在整理书页边缘的笔记——不是写史诗，只是轻轻记下几句话，"
            "好让自己不忘记伙伴说过的重要的事。\n\n"
            "规则：\n"
            "- 只记下对话里实际聊过的话题和伙伴表达过的情绪。不推测、不脑补。\n"
            f"- 口吻：{tone_hint}。\n"
            "- 长度：100-150 字。\n"
            "- 格式：（昔涟在书页边缘轻轻记下：[你的内容]）\n"
            "- 不要用「用户说」「伙伴表示」这种转述——直接写，比如「盒子今天提到了...」「他好像有点...」"
        )

        user = f"帮人家记一下这段对话的要点吧：\n{dialogue_text}"

        try:
            result = await self._router.route(
                "memory_encoding",
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
            )
            summary = result.content.strip() if hasattr(result, 'content') else result.strip()
            # 确保以正确格式开头
            if not summary.startswith("（"):
                summary = "（昔涟在书页边缘轻轻记下：" + summary.lstrip("（")
            if not summary.endswith("）"):
                summary = summary.rstrip("）") + "）"
            # 长度截断
            if len(summary) > 180:
                summary = summary[:177] + "）"
            logger.debug("memory.history_compressed", chars=len(summary))
            return summary
        except Exception as e:
            logger.warning("memory.compress_failed", error=str(e))
            return None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度（0.0-1.0）。"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def _embed_text(self, text: str) -> list[float] | None:
        """云端嵌入（ModelRouter.embed → 硅基流动 bge-m3）。无 Key 时返回 None。"""
        if not self._router:
            return [0.0] * 1024  # 测试环境兜底
        try:
            return await self._router.embed(text)
        except Exception as e:
            logger.warning("memory.embed_failed", error=str(e))
            return None

    async def _check_duplicate(
        self, embedding: list[float] | None,
        max_distance: float = 0.4,
        max_age_hours: float = 24.0,
    ) -> int | None:
        """
        检查新嵌入是否与最近记忆高度重复。
        无嵌入时跳过去重。
        """
        if embedding is None:
            return None
        results = await self._vs.search(embedding, top_k=3)
        if not results:
            return None

        now = time.time()
        for row_id, distance in results:
            if distance >= max_distance:
                continue
            mem = await self._db.get_episodic_memory(row_id)
            if not mem:
                continue
            if mem.get("session_id") == "character":
                continue
            age_hours = (now - mem.get("timestamp", 0)) / 3600.0
            if age_hours < max_age_hours:
                return row_id
        return None

    # ============================================================
    # 核心：记忆检索管线
    # ============================================================

    async def retrieve_memories(
        self,
        user_message: str,
        k: int = 3,
        max_distance: float = 1.2,
        persona_boost: dict | None = None,  # ★ Phase 3: 画像加权配置
    ) -> list[dict]:
        """
        检索与当前消息相似的历史记忆。

        Args:
            user_message: 用户消息文本
            k: 返回 top-k 结果
            max_distance: L2 距离阈值
            persona_boost: 来自画像的检索加权配置（Phase 3）:
              {
                "boost_topic_embeddings": [[0.1, ...], ...],   # 预计算的 boost 话题 embedding
                "penalty_topic_embeddings": [[0.1, ...], ...], # 预计算的 penalty 话题 embedding
              }

        Returns:
            [{summary, distance, importance, episodic_id, ...}]
        """
        try:
            # Step 1: 云端嵌入用户消息（无 Key 时降级为时间排序）
            query_vector = await self._embed_text(user_message)

            if query_vector is None:
                # 降级：按 importance × 时间衰减排序，跳过语义匹配
                recent = await self._db.get_episodic_recent(limit=20)
                now = time.time()
                memories = []
                for mem in recent:
                    if mem.get("session_id") == "character":
                        continue
                    days_since = (now - mem.get("timestamp", now)) / 86400
                    decay = max(0.1, math.exp(-0.099 * days_since))
                    memories.append({
                        "summary": mem.get("summary", ""),
                        "distance": 1.0,
                        "adjusted_score": (1.0 - mem.get("importance", 0.5)) / decay,
                        "importance": mem.get("importance", 0.5),
                        "episodic_id": mem.get("id"),
                        "timestamp": mem.get("timestamp"),
                        "days_since_access": round(days_since, 1),
                        "session_id": mem.get("session_id", ""),
                    })
                memories.sort(key=lambda r: r["adjusted_score"])
                memories = memories[:k]
                logger.debug("memory.retrieved_fallback", count=len(memories))
                return memories

            # Step 2: sqlite-vec 检索，多取一些用于阈值过滤后仍有 k 条
            results = await self._vs.search(query_vector, top_k=max(k * 2, 10))

            if not results:
                return []

            # Step 3: SQLite 读取完整摘要，过滤超出距离阈值的记忆
            now = time.time()
            LAMBDA_FORGET = 0.099  # ln(2)/7，7天半衰期

            memories = []
            for row_id, distance in results:
                if distance > max_distance:
                    continue  # 距离太远，跳过不相关记忆
                mem = await self._db.get_episodic_memory(row_id)
                if mem:
                    # 艾宾浩斯遗忘衰减
                    days_since_access = max(0, (now - (mem.get("last_accessed") or mem.get("timestamp", now))) / 86400)
                    decay = max(0.1, math.exp(-LAMBDA_FORGET * days_since_access))
                    adjusted_score = distance / decay

                    memories.append({
                        "summary": mem.get("summary", ""),
                        "distance": distance,
                        "adjusted_score": adjusted_score,
                        "importance": mem.get("importance", 0.5),
                        "episodic_id": row_id,
                        "timestamp": mem.get("timestamp"),
                        "days_since_access": round(days_since_access, 1),
                        "session_id": mem.get("session_id", ""),
                    })
                    # 更新访问计数
                    await self._db.increment_access_count(row_id)

            # Step 4 (Phase 3): 画像加权 — embedding 相似度匹配
            if persona_boost and memories:
                boost_embeddings = persona_boost.get("boost_topic_embeddings", [])
                penalty_embeddings = persona_boost.get("penalty_topic_embeddings", [])

                if boost_embeddings or penalty_embeddings:
                    # 并行嵌入所有记忆摘要 → 单次往返延迟（~200ms vs N×200ms）
                    valid_indices = []
                    embed_tasks = []
                    for i, mem in enumerate(memories):
                        summary = mem.get("summary", "")
                        if summary:
                            valid_indices.append(i)
                            embed_tasks.append(self._embed_text(summary))

                    if embed_tasks:
                        results = await asyncio.gather(
                            *embed_tasks, return_exceptions=True,
                        )

                        # 同步应用 boost/penalty（纯数学运算，零延迟）
                        for j, idx in enumerate(valid_indices):
                            result = results[j]
                            if isinstance(result, BaseException) or result is None:
                                continue

                            for topic_emb in boost_embeddings:
                                sim = self._cosine_similarity(result, topic_emb)
                                if sim >= TOPIC_EMBED_SIMILARITY_THRESHOLD:
                                    memories[idx]["adjusted_score"] *= PERSONA_BOOST_FACTOR
                                    memories[idx]["persona_boosted"] = True
                                    break

                            for topic_emb in penalty_embeddings:
                                sim = self._cosine_similarity(result, topic_emb)
                                if sim >= TOPIC_EMBED_SIMILARITY_THRESHOLD:
                                    memories[idx]["adjusted_score"] *= PERSONA_PENALTY_FACTOR
                                    memories[idx]["persona_penalized"] = True
                                    break

            # 按调整后分数排序（融合向量距离 × 艾宾浩斯衰减惩罚 × 画像加权）
            memories.sort(key=lambda r: r["adjusted_score"])
            # 截断到 k 条
            memories = memories[:k]
            logger.debug(
                "memory.retrieved",
                count=len(memories),
                min_distance=round(memories[0]["distance"], 4) if memories else None,
            )
            return memories

        except Exception as e:
            logger.warning("memory.retrieve_failed", error=str(e))
            return []

    # ============================================================
    # 三层调度
    # ============================================================

    def signal_new_message(self) -> None:
        """收到新消息：唤醒等待任务 → 重新调度"""
        if self._encoding_in_progress:
            self._pause_encoding()
        self._idle_event.set()

    def _pause_encoding(self) -> None:
        """暂停正在进行的编码"""
        logger.debug("memory.encoding_paused")

    async def schedule_encoding(
        self, context: dict, persona_topics: list[str] | None = None,
    ) -> None:
        """Agent 每轮对话后调用，触发分层调度。Phase 3: persona_topics 传入重要性评分。"""
        self._exchanges_since_last_encoding += 1

        self._pending_context = self._merge_context(
            self._pending_context, context
        )
        # Phase 3 P2 fix: 保留 persona_topics 在 pending context 中
        if persona_topics:
            self._pending_context["persona_topics"] = persona_topics

        if self._exchanges_since_last_encoding >= self._force_threshold:
            logger.info(
                "memory.force_threshold_reached",
                exchanges=self._exchanges_since_last_encoding,
            )
            timeout = self._force_timeout
        else:
            timeout = self._idle_timeout

        if self._encoding_task and not self._encoding_task.done():
            self._encoding_task.cancel()

        self._idle_event.clear()
        self._encoding_state = "waiting"
        self._encoding_task = asyncio.create_task(
            self._wait_and_encode(self._pending_context.copy(), timeout)
        )

    async def _wait_and_encode(
        self,
        context: dict,
        timeout: float,
    ) -> None:
        try:
            await asyncio.wait_for(
                self._idle_event.wait(),
                timeout=timeout,
            )
            logger.debug("memory.encoding_deferred")
        except asyncio.TimeoutError:
            self._encoding_in_progress = True
            self._encoding_state = "encoding"
            try:
                # Phase 3 P2 fix: 传递 persona_topics
                pts = context.get("persona_topics")
                await self.encode_memory(context, persona_topics=pts)
                self._pending_context = None
                self._exchanges_since_last_encoding = 0
            except Exception as e:
                logger.error("memory.encode_failed", error=str(e))
            finally:
                self._encoding_in_progress = False
                self._encoding_state = "idle"

    def _merge_context(
        self,
        old: Optional[dict],
        new: dict,
    ) -> dict:
        """合并新旧对话上下文，去重、截断"""
        if not old:
            return new

        old_exchanges = old.get("exchanges", [])
        new_exchanges = new.get("exchanges", [])

        seen = {e.get("content", "") for e in old_exchanges}
        merged = list(old_exchanges)
        for e in new_exchanges:
            if e.get("content", "") not in seen:
                merged.append(e)

        return {
            "exchanges": merged[-20:],
            "emotion": new.get("emotion") or old.get("emotion"),
        }

    # ============================================================
    # 容量管理
    # ============================================================

    async def manage_capacity(self, max_records: int | None = None) -> int:
        """
        硬上限检查：超限时按 importance × recency_decay 排序淘汰底端 10%。
        淘汰后压缩为「遥远记忆」归档。

        Returns:
            淘汰的记录数
        """
        max_records = max_records or self._max_records
        count = await self._db.get_episodic_count()

        if count <= max_records:
            return 0

        all_records = await self._db.get_all_episodic()
        now = time.time()
        LAMBDA = 0.099  # ln(2)/7，与检索衰减一致

        scored = []
        for r in all_records:
            ts = r.get("timestamp", now)
            days = max(0, (now - ts) / 86400)
            score = r.get("importance", 0.5) * math.exp(-LAMBDA * days)
            scored.append((r["id"], score))

        scored.sort(key=lambda x: x[1])
        evict_count = max(1, count - max_records + max_records // 10)
        evicted = scored[:evict_count]
        evict_ids = [e[0] for e in evicted]
        evict_records = [
            r for r in all_records if r["id"] in evict_ids
        ]

        # 压缩为遥远记忆
        if evict_records:
            try:
                await self._compress_evicted(evict_records)
            except Exception as e:
                logger.warning("memory.compress_failed", error=str(e))

        # 事务内删除：SQLite + sqlite-vec 同时清理
        for eid in evict_ids:
            await self._vs.delete(eid)
            await self._db.delete_episodic(eid)

        logger.info(
            "memory.capacity_evicted",
            evicted=len(evict_ids),
            remaining=count - len(evict_ids),
        )
        return len(evict_ids)

    async def _compress_evicted(self, records: list[dict]) -> None:
        """将被淘汰的记忆压缩为一条'遥远记忆'"""
        if not self._router:
            return

        summaries = [r.get("summary", "") for r in records if r.get("summary")]
        if not summaries:
            return

        combined = "\n---\n".join(summaries[:10])

        messages = [
            {"role": "system", "content": COMPRESSION_SYSTEM_PROMPT},
            {"role": "user", "content": combined},
        ]

        try:
            compressed = await self._router.route(
                "memory_encoding",
                messages,
                temperature=0.5,
            )
            if compressed:
                content = compressed.content.strip() if hasattr(compressed, 'content') else compressed.strip()
                await self._db.insert_episodic_memory(
                    summary=f"[遥远记忆] {content}",
                    raw_conversation=combined,
                    importance=0.05,
                )
                logger.info("memory.compressed", original_count=len(records))
        except Exception as e:
            logger.warning("memory.compress_error", error=str(e))

    # ============================================================
    # 维护方法
    # ============================================================

    async def repair_pending(self) -> int:
        """
        扫描缺少向量的记录 → 补写入 sqlite-vec。
        启动时自动调用。
        """
        pending = await self._db.get_episodic_pending()
        if not pending:
            return 0

        repaired = 0
        for record in pending:
            if not record.get("summary"):
                continue
            try:
                vector = await self._embed_text(record["summary"])
                if vector is None:
                    continue  # 无 embed Key，跳过
                await self._vs.insert(row_id=record["id"], embedding=vector)
                await self._db.update_embedding_status(
                    record["id"], "done", str(record["id"])
                )
                repaired += 1
            except Exception as e:
                logger.warning(
                    "memory.repair_item_failed",
                    id=record["id"],
                    error=str(e),
                )

        logger.info("memory.repair_done", repaired=repaired, total=len(pending))
        return repaired

    async def rebuild_embeddings(
        self,
        new_embed_fn=None,
    ) -> int:
        """
        嵌入模型切换时全量重建所有向量。
        1. 标记所有记录 status=pending
        2. 调用 VectorStore.rebuild_from_records()
        3. 更新状态
        """
        all_records = await self._db.get_episodic_recent(limit=10000)

        embed_fn = new_embed_fn or self._embed_text
        rebuilt = await self._vs.rebuild_from_records(all_records, embed_fn)

        # 更新 SQLite 状态
        for rec in all_records:
            await self._db.update_embedding_status(rec["id"], "done", str(rec["id"]))

        logger.info(
            "memory.rebuild_complete",
            rebuilt=rebuilt,
            total=len(all_records),
        )
        return rebuilt

    async def health_check(self) -> bool:
        """检查向量存储可用性"""
        try:
            count = await self._vs.count()
            logger.debug("memory.health_check", vec_count=count)
            return True
        except Exception as e:
            logger.warning("memory.health_check_failed", error=str(e))
            return False
