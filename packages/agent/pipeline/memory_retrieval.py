"""MemoryRetrievalProcessor — 记忆检索管线"""

from loguru import logger

from ._base import ServiceModule


class MemoryRetrievalProcessor(ServiceModule):
    """记忆检索。依赖 router（embedding）、memory_manager、db（角色记忆检查）."""

    # 角色记忆触发关键词
    _CHARACTER_KEYWORDS: tuple[str, ...] = (
        "你以前", "小时候", "轮回", "翁法罗斯", "白厄", "迷迷",
        "哀丽秘榭", "黄金裔", "铁墓", "德谬歌", "逐火之旅",
        "阿格莱雅", "万敌", "赛飞儿", "那刻夏", "风堇",
        "遐蝶", "海瑟音", "刻律德菈", "缇宝", "缇安",
        "浮黎", "记忆星神", "黑潮", "泰坦", "如我所书",
        "你的过去", "你来自哪里", "你以前住", "你经历过",
        "你等过", "三千万", "开拓者",
    )

    def __init__(self, ctx, router=None, db=None):
        super().__init__(ctx, router=router, db=db)
        self._memory_manager = None
        self._portrait_manager = None

    def set_managers(self, memory_manager, portrait_manager, db=None):
        """注入异步初始化的管理器（由 AgentCore.startup() 调用）。"""
        self._memory_manager = memory_manager
        self._portrait_manager = portrait_manager
        if db is not None:
            self._db = db

    async def retrieve_memories(self, user_message: str) -> list[dict] | None:
        """检索与当前消息相关的历史记忆 + 角色情景记忆。"""
        if len(user_message.strip()) < 5:
            return None

        try:
            if not self._memory_manager:
                return None

            persona_boost = None
            if self._portrait_manager:
                cached = getattr(self._ctx, '_persona_boost_config', None)
                cached_version = cached.get("_l1_version") if cached else None
                current_l1 = self._ctx._current_l1_version
                if cached and cached_version == current_l1:
                    persona_boost = cached
                else:
                    try:
                        persona_boost = await self._portrait_manager.build_retrieval_config()
                        self._ctx._persona_boost_config = persona_boost
                    except Exception:
                        persona_boost = {}
                        self._ctx._persona_boost_config = {}

            results = await self._memory_manager.retrieve_memories(
                user_message, k=5, persona_boost=persona_boost,
            )
            if not results:
                return None

            user_mems = []
            char_mems = []
            for r in results:
                if r.get("session_id") == "character":
                    char_mems.append(r)
                else:
                    user_mems.append(r)

            triggered = any(kw in user_message for kw in self._CHARACTER_KEYWORDS)
            if triggered and char_mems:
                self._ctx.character_memory_retrieval = char_mems[:2]
                logger.debug("memory.character_triggered",
                             keywords=[kw for kw in self._CHARACTER_KEYWORDS if kw in user_message],
                             count=min(len(char_mems), 2))
            else:
                self._ctx.character_memory_retrieval = None

            logger.debug("memory.retrieved", user=len(user_mems), char=len(char_mems), triggered=triggered)
            return user_mems[:3] if user_mems else None

        except Exception as e:
            logger.warning("memory.retrieval_failed", error=str(e))
            return None
