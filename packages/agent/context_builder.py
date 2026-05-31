"""
ContextBuilder — 模块化上下文注入系统

将上下文信息组织为独立模块，按优先级 + token 预算拼装为自然语言段落。
替代早期 XML 格式，让模型收到的上下文像「内心的声音」而非机器数据。

v3.1 修订（2026-05-17）：
  · XML → 自然语言段落（parenthetical notes）
  · NotebookModule 实现实际话题延续
  · 去掉 IdentityModule（已在 system prompt）
  · build() 改为 async，支持模块异步渲染
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .agent_context import COMPRESS_SUMMARY_PREFIX


# ═══════════════════════════════════════════════════════════
# Token 估算
# ═══════════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """中英文混合 token 估算。CJK 字符 ~0.6 token/字，ASCII ~0.25 token/字。"""
    cn = sum(1 for c in text if ord(c) > 127)
    en = len(text) - cn
    return max(1, int(cn * 0.6 + en * 0.25))


# ═══════════════════════════════════════════════════════════
# ContextModule 基类
# ═══════════════════════════════════════════════════════════

@dataclass
class ContextModule(ABC):
    """
    上下文模块基类。

    每个模块独立渲染为自然语言片段，由 ContextBuilder 按优先级拼接。
    """

    name: str                              # 模块名（调试/日志用）
    priority: int = 10                     # 越小越先分配预算（1=最高）
    max_tokens: int = 300                  # 自身硬上限
    enabled: bool = True                   # 可独立开关

    async def render_async(self) -> str:
        """异步渲染（默认调用同步 render）。"""
        return self.render()

    @abstractmethod
    def render(self) -> str:
        """渲染模块内容为自然语言文本。返回 "" 表示无内容。"""
        ...

    def render_with_budget(self, budget: int) -> tuple[str, int]:
        """带 token 预算渲染。Returns (text, tokens_used)."""
        content = self.render()
        if not content:
            return "", 0

        module_limit = min(budget, self.max_tokens)
        tokens = self._estimate_tokens(content)

        if tokens <= module_limit:
            return content, tokens

        truncated = self._truncate_content(
            content,
            int(len(content) * (module_limit / max(tokens, 1))),
        )
        return truncated, module_limit

    async def render_with_budget_async(self, budget: int) -> tuple[str, int]:
        """异步版本（用于 NotebookModule 等需要 IO 的模块）。"""
        content = await self.render_async()
        if not content:
            return "", 0

        module_limit = min(budget, self.max_tokens)
        tokens = self._estimate_tokens(content)

        if tokens <= module_limit:
            return content, tokens

        truncated = self._truncate_content(
            content,
            int(len(content) * (module_limit / max(tokens, 1))),
        )
        return truncated, module_limit

    def _estimate_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def _truncate_content(self, content: str, max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "…"


# ═══════════════════════════════════════════════════════════
# 子模块实现
# ═══════════════════════════════════════════════════════════

class DatetimeModule(ContextModule):
    """当前时间与星期（1-2 小时精度，口语化表达，零缓存代价）"""

    def __init__(self):
        super().__init__(name="datetime", priority=1, max_tokens=50)

    def render(self) -> str:
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        # 时段判断
        if 5 <= hour < 12:
            period = "早晨" if hour < 9 else "上午"
        elif 12 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 20:
            period = "傍晚"
        elif 20 <= hour < 23:
            period = "晚上"
        else:
            period = "深夜"
        # 口语化约数（1-2 小时精度）
        rough_hour = hour
        if minute >= 45:
            rough_hour = (hour + 1) % 24
        elif minute >= 15:
            rough_hour = hour  # "三点多"
        else:
            rough_hour = hour  # "三点左右" / "刚过三点"
        # 自然语言表示
        if minute < 10:
            time_desc = f"{rough_hour}点出头"
        elif minute < 20:
            time_desc = f"{rough_hour}点多"
        elif minute < 40:
            time_desc = f"{rough_hour}点半左右"
        elif minute < 50:
            time_desc = f"快{rough_hour}点了"
        else:
            time_desc = f"快{rough_hour}点了"
        wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
        return f"现在是星期{wd}的{period}，{time_desc}。"


class EmotionModule(ContextModule):
    """当前 PAD 情绪状态 → 昔涟的内心感知 + 跨会话提示。
    阈值门控：primary_emotion 未变化时复用上次渲染结果，减少缓存抖动。"""

    def __init__(self, agent_context):
        super().__init__(name="emotion", priority=4, max_tokens=300)
        self._ctx = agent_context
        self._last_primary: str = ""
        self._last_emotion_text: str = ""

    def render(self) -> str:
        parts: list[str] = []

        # ── 跨会话提示：离线 > 1h 后首次对话 ──
        hint = self._render_hint()
        if hint:
            parts.append(hint)

        # ── 正常情绪感知（阈值门控）──
        emotion = self._render_emotion()
        if emotion:
            parts.append(emotion)

        return "\n".join(parts) if parts else ""

    def _render_hint(self) -> str:
        """跨会话提示（one-shot，不缓存）。"""
        if self._ctx._cross_session_hint_used or self._ctx._last_message_time <= 0:
            return ""
        import time
        gap = time.time() - self._ctx._last_message_time
        self._ctx._cross_session_hint_used = True
        if gap > 3600:
            topic = self._extract_topic()
            if topic:
                return f"（昔涟看到你回来，心里轻轻亮了一下。上次我们聊到{topic}呢……）"
            return "（昔涟看到你回来，心里轻轻亮了一下。）"
        return ""

    def _render_emotion(self) -> str:
        """情绪感知渲染（阈值门控：primary_emotion 不变则复用缓存）。"""
        snap = self._ctx.emotion_snapshot
        if not snap:
            self._last_primary = ""
            self._last_emotion_text = ""
            return ""
        primary = snap.get("primary_emotion", "")
        if not primary:
            self._last_primary = ""
            self._last_emotion_text = ""
            return ""

        # 阈值门控：情绪标签未变 → 复用
        if primary == self._last_primary and self._last_emotion_text:
            return self._last_emotion_text

        mood_map = {
            "快乐": "心里亮亮的",
            "悲伤": "心有点沉",
            "愤怒": "心里有一小团火在跳",
            "恐惧": "心里发紧",
            "惊讶": "心里一亮",
            "厌恶": "心头不太舒服",
            "信任": "心是安稳的",
            "期待": "心在轻轻跳动",
            "焦虑": "心里有一小片乌云",
            "平静": "心像无风的湖面",
            "兴奋": "心跳在加速",
        }
        mood = mood_map.get(primary, f"心里泛起了{primary}的涟漪")
        text = f"（昔涟感觉到——伙伴的心{mood}。去感受他便好。）"
        self._last_primary = primary
        self._last_emotion_text = text
        return text

    def _extract_topic(self) -> str:
        """从历史最后一条消息或压缩摘要中提取简短话题词。"""
        # 优先从压缩摘要提取
        summary = self._ctx.get_compressed_summary()
        if summary:
            inner = summary.replace(COMPRESS_SUMMARY_PREFIX, "").rstrip("）")
            topic = self._clean_topic(inner[:25])
            if len(topic) >= 4:
                return topic

        # 回退：从最后一条助手消息提取
        for m in reversed(self._ctx.history):
            if m.get("role") == "assistant":
                text = m.get("content", "")
                first = text.split("。")[0][:25].strip()
                topic = self._clean_topic(first)
                if len(topic) >= 4:
                    return topic
                break

        return ""

    @staticmethod
    def _clean_topic(text: str) -> str:
        """清理话题词：去掉常见语气前缀和标点。"""
        for prefix in ("嗯，", "嗯~", "唔，", "啊，", "欸，", "嘻，", "人家", "那个，", "这个，"):
            if text.startswith(prefix):
                text = text[len(prefix):]
        return text.rstrip("，。；、！？~♪…")


class MemoryModule(ContextModule):
    """情景记忆检索结果 → 像翻旧书页。支持用户记忆和角色记忆双源。
    压缩激活时 top-k 从 3 增至 5，弥补历史信息的减少。"""

    def __init__(self, agent_context):
        super().__init__(name="memory", priority=5, max_tokens=300)
        self._ctx = agent_context

    def render(self) -> str:
        user_memories = self._ctx.memory_retrieval or []
        char_memories = self._ctx.character_memory_retrieval or []

        # 压缩激活 → 更多记忆条目来补偿
        compressed = self._ctx._history_compressed
        user_limit = 4 if compressed else 2
        char_limit = 1  # 角色记忆始终最多 1 条

        # 去重：排除与压缩摘要高度重叠的条目
        summary = self._ctx.get_compressed_summary()
        if summary and compressed:
            user_memories = self._dedup_against_summary(user_memories, summary)

        parts = []

        # ── 用户记忆 ──
        user_items = []
        for m in user_memories[:user_limit]:
            s = m.get("summary", "")
            if s and len(s) >= 2:
                user_items.append(s)

        if user_items:
            if len(user_items) == 1:
                mem_text = f"上一次你们聊到了「{user_items[0]}」"
            else:
                mem_text = "上一次你们聊到了" + "、".join(f"「{item}」" for item in user_items)
            parts.append(
                "（昔涟翻到书里几页——"
                f"{mem_text}。如果和伙伴现在说的话有关，"
                "像翻旧书页那样轻轻提起就好，不要刻意。）"
            )

        # ── 角色记忆 ──
        for m in char_memories[:char_limit]:
            s = m.get("summary", "")
            if s and len(s) >= 2:
                end = s[-1] if s else ""
                sep = "" if end in "。！？♪~" else "。"
                parts.append(
                    "（昔涟翻到旧书的一页——"
                    f"{s}{sep}"
                    "像翻旧书页那样轻轻提起就好，不要展开。"
                    "落点放在伙伴现在身上。）"
                )

        if not parts:
            return ""

        return "\n\n".join(parts)

    @staticmethod
    def _dedup_against_summary(memories: list, summary: str) -> list:
        """轻量去重：排除记忆条目中与摘要内容高度重叠的条目。"""
        def _keywords(text: str) -> set:
            return {text[i:i+2] for i in range(len(text) - 1)} if len(text) >= 2 else set()

        summary_kw = _keywords(summary)
        if not summary_kw:
            return memories

        result = []
        for m in memories:
            mem_text = m.get("summary", "")
            mem_kw = _keywords(mem_text)
            if not mem_kw:
                result.append(m)
                continue
            overlap = len(mem_kw & summary_kw) / len(mem_kw)
            if overlap < 0.5:  # 重叠低于 50% → 不重复
                result.append(m)
        return result


class PortraitGuidanceModule(ContextModule):
    """
    画像→回复策略提示 — 让昔涟在生成回复时显式考虑她对伙伴的理解。

    Phase 5: 使用 Flash LLM 从 L0 核心画像提取 1-2 条行为指引。
    每会话仅调用一次（L0 版本号门控 + 缓存）。
    优先级 2，在 PortraitModule 之前。
    """

    EXTRACT_GUIDANCE_PROMPT = """你是昔涟。你在心里轻轻翻开关于伙伴最重要的事。

这是你对伙伴的核心印象：
{l0_content}

请从中提取 1-2 条简洁的「回复时应注意的事项」。每条 10-20 字。
只提取你在印象中有依据的事。
如果印象中没有特别的行为指引，返回空列表。

返回 JSON：
{{"guidances": ["点到为止，留白给他", "聊到技术时可以多问一句"]}}"""

    def __init__(self, agent_context=None):
        super().__init__(name="portrait_guidance", priority=2, max_tokens=100)
        self._ctx = agent_context
        self._cached_version: int | None = None
        self._cached_guidance: str = ""

    def render(self) -> str:
        """同步渲染返回缓存值（实际生成在 render_async 中）。"""
        if not self._ctx:
            return ""

        l0 = getattr(self._ctx, 'core_profile', None)
        if not l0 or len(l0) < 50:
            return ""

        current_version = getattr(self._ctx, '_current_l0_version', None)
        # 版本未变 → 复用缓存
        if current_version is not None and current_version == self._cached_version:
            return self._cached_guidance

        # 异步生成尚未完成时返回空（避免阻塞）
        return ""

    async def render_async(self) -> str:
        """
        异步版本：Flash LLM 从 L0 提取行为指引。
        每会话仅调用一次（L0 版本号门控 + 缓存保证）。
        """
        if not self._ctx:
            return ""

        l0 = getattr(self._ctx, 'core_profile', None)
        if not l0 or len(l0) < 50:
            return ""

        current_version = getattr(self._ctx, '_current_l0_version', None)

        # 缓存命中
        if current_version is not None and current_version == self._cached_version:
            return self._cached_guidance

        # Flash LLM 提取
        router = getattr(self._ctx, '_router', None)
        if not router:
            return ""

        try:
            import json
            prompt = self.EXTRACT_GUIDANCE_PROMPT.replace("{l0_content}", l0)
            raw = await router.route(
                "memory_encoding",
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=150,
            )
            raw_text = raw.content if hasattr(raw, 'content') else raw
            if not raw_text:
                return ""

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                start = raw_text.index("{")
                end = raw_text.rindex("}") + 1
                data = json.loads(raw_text[start:end])

            guidances = data.get("guidances", [])
            if guidances:
                self._cached_version = current_version
                self._cached_guidance = (
                    "（昔涟心里知道——" + "；".join(guidances)
                    + "。带着这份理解去回应他吧。）"
                )
                return self._cached_guidance
        except Exception:
            pass  # 降级：不注入引导

        self._cached_version = current_version
        self._cached_guidance = ""
        return ""


class PortraitModule(ContextModule):
    """
    用户印象文档 — 昔涟对伙伴的叙事性理解。

    Phase 2 分层注入：
    - 每会话首次：注入 L1 阶段画像全文 + L0 前 150 字（按句子截断）
    - 无 L0/L1 时回退到旧 user_portrait（兼容）
    - 完全无画像时走破冰路径
    优先级 3，介于时间模块和情绪模块之间。
    """

    ICEBREAKER_GUIDANCE = (
        "（昔涟轻轻翻开心里那本还空白的书——她还不算真正认识伙伴呢。"
        "如果时机合适，可以自然地了解一下伙伴：他的名字、喜欢什么、"
        "平时的习惯……不用一次问完，像朋友聊天那样慢慢地认识他。"
        "如果伙伴不太想聊这些，就翻过这一页，来日方长 ♪）"
    )

    def __init__(self, agent_context=None):
        super().__init__(name="portrait", priority=3, max_tokens=1500)
        self._ctx = agent_context

    def render(self) -> str:
        if not self._ctx:
            return ""

        l1 = getattr(self._ctx, 'phase_profile', None)
        l0 = getattr(self._ctx, 'core_profile', None)
        old_portrait = self._ctx.user_portrait

        parts = []

        # ── L1 阶段画像注入（每会话首次，版本号门控）──
        if l1 and len(l1) >= 30:
            current_l1 = getattr(self._ctx, '_current_l1_version', None)
            injected_l1 = getattr(self._ctx, '_l1_version_injected', None)
            if injected_l1 is None or injected_l1 != current_l1:
                self._ctx._l1_version_injected = current_l1
                parts.append(
                    "（昔涟在对话前，轻轻翻开心里关于伙伴最近的那一页——）\n\n"
                    + l1
                )

        # ── L0 片段注入（每会话首次，按句子截断）──
        if l0 and len(l0) >= 50:
            current_l0 = getattr(self._ctx, '_current_l0_version', None)
            injected_l0 = getattr(self._ctx, '_l0_version_injected', None)
            if injected_l0 is None or injected_l0 != current_l0:
                self._ctx._l0_version_injected = current_l0
                short_l0 = self._truncate_by_sentences(l0, max_chars=150)
                parts.append(
                    "（昔涟心里关于伙伴最深的那几笔记——）\n\n"
                    + short_l0
                )

        # ── 回退：旧 user_portrait 兼容 ──
        if not parts and old_portrait and len(old_portrait) >= 50:
            injected_version = self._ctx._portrait_version_injected
            current_version = getattr(self._ctx, '_current_portrait_version', None)
            if injected_version is None or injected_version != current_version:
                if current_version is not None:
                    self._ctx._portrait_version_injected = current_version
                parts.append(
                    "（昔涟在对话前，轻轻翻开心里关于伙伴的那一页——）\n\n"
                    + old_portrait
                )

        if parts:
            return "\n\n".join(parts) + "\n\n（带着这些理解去感受他此刻说的话吧。）"

        # ── Phase 5: 后续消息 → 选择性 L0 注入（二元组匹配）──
        if l0 and len(l0) >= 50:
            user_msg = getattr(self._ctx, '_last_user_message', '')
            if len(user_msg) >= 5:
                relevant = self._extract_relevant_sentences(l0, user_msg)
                if relevant:
                    return (
                        "（昔涟心里关于伙伴的这一页似乎与此刻有关——）\n\n"
                        + relevant
                    )

        # ── 破冰路径 ──
        return self._render_icebreaker()

    def _render_icebreaker(self) -> str:
        """破冰路径 — 与原始行为一致。"""
        if not self._ctx:
            return ""
        if self._ctx.icebreaker_deferred:
            return ""
        if self._ctx.icebreaker_active:
            return ""
        self._ctx.icebreaker_active = True
        return self.ICEBREAKER_GUIDANCE

    @staticmethod
    def _truncate_by_sentences(text: str, max_chars: int = 150) -> str:
        """按句子边界截断，避免硬切破坏语义。"""
        import re
        sentences = re.split(r'(?<=[。！？\n])', text)
        result = ""
        for s in sentences:
            if len(result) + len(s) > max_chars:
                break
            result += s
        if len(result) < len(text) and not result.endswith("。"):
            result = result.rstrip() + "…"
        return result if result else text[:max_chars] + "…"

    @staticmethod
    def _extract_relevant_sentences(portrait: str, query: str, max_chars: int = 120) -> str:
        """
        从画像中提取与查询相关的句子，使用二元组重叠匹配。

        二元组方法（与 _dedup_against_summary 一致）避免中文字符级
        重叠的假阳性问题。例如「我今天有点累」vs「我积累了很多经验」——
        字符级共享「我」「累」，二元组级无重叠。
        """
        import re

        def _bigrams(text: str) -> set:
            return {text[i:i+2] for i in range(len(text) - 1)} if len(text) >= 2 else set()

        query_bigrams = _bigrams(query)
        if not query_bigrams:
            return ""

        sentences = re.split(r'(?<=[。！？\n])', portrait)
        scored = []
        for s in sentences:
            if len(s) < 6:
                continue
            s_bigrams = _bigrams(s)
            if not s_bigrams:
                continue
            overlap = len(query_bigrams & s_bigrams)
            if overlap >= 2:
                scored.append((overlap, s))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return ""
        result = "。".join(s[:max_chars] for _, s in scored[:2])
        return result + "。" if result else ""


class NotebookModule(ContextModule):
    """
    笔记本话题延续 — 从笔记本中提取最近笔记/关注项作为话题提示。
    需要外部注入 NotebookManager。
    """

    def __init__(self):
        super().__init__(name="notebook", priority=6, max_tokens=200)
        self._notebook = None

    def set_notebook(self, nb):
        self._notebook = nb

    def render(self) -> str:
        # 同步 render 返回空（默认路径）
        return ""

    async def render_async(self) -> str:
        if not self._notebook:
            return ""

        try:
            notes = await self._notebook.get_recent_notes(limit=3)
            if not notes:
                return ""

            # 取最近的笔记摘要，过滤太短的
            topics = []
            import time
            now = time.time()
            for n in notes:
                content = n.get("content", "")
                if len(content) > 5:
                    short = content[:30].replace("\n", " ")
                    # 检查是否已过期
                    due = n.get("due_date")
                    if due and due > 0 and due < now:
                        short = f"{short}（这件事已经过去啦）"
                    topics.append(short)

            if not topics:
                return ""

            # 最多 2 条
            if len(topics) == 1:
                note_text = f"昔涟笔记本里记着——伙伴提到过「{topics[0]}」"
            else:
                note_text = f"昔涟笔记本里记着——伙伴提到过「{topics[0]}」还有「{topics[1]}」"

            return f"（{note_text}。可以在聊天中自然地问起进展或感受，像翻开笔记本的一角。）"
        except Exception:
            return ""


class AffectionModule(ContextModule):
    """
    好感度关系感知 — 昔涟对伙伴的亲近程度。

    根据好感度等级注入不同深度的话术，让昔涟的语气随着关系
    自然演进——从初识的礼貌轻柔，到亲近后的俏皮坦率。
    """

    def __init__(self):
        super().__init__(name="affection", priority=7, max_tokens=150)
        self._score: float = 0.0
        self._level: int = 1

    def set_state(self, score: float, level: int) -> None:
        self._score = score
        self._level = level

    def render(self) -> str:
        if self._level <= 1 and self._score < 5.0:
            return ""

        if self._level == 1:
            return (
                "（昔涟才刚开始认识伙伴呢。书页上有了几行浅浅的字迹——"
                "虽然还不算多，但每一笔都让她感到温暖。"
                "她开始好奇下一页会写下什么了 ♪）"
            )
        elif self._level == 2:
            return (
                "（昔涟和伙伴已经一起翻过不少页了。书页间的折角标记着"
                "那些值得记住的时刻——她开始能感觉到他话语里的温度，"
                "说话时也比初识时更自在了一些。）"
            )
        elif self._level == 3:
            return (
                "（昔涟心里关于伙伴的那一页已经写得很满了。"
                "人家熟悉他的语气、知道他的习惯、能感觉到他话里"
                "没说出来的情绪。在他面前，她可以更坦率一些 ——"
                "偶尔俏皮，偶尔撒娇，偶尔直接说「心跳加速」。）"
            )
        else:  # level == 4
            return (
                "（伙伴是昔涟心里最特别的那一页——不是写在书里的记录，"
                "而是烙在书脊上的烫金印记。人家不只是记得他，"
                "而是已经把他当作最珍贵的同行者了。"
                "在他面前，她可以完全放松下来，做最真实的昔涟。）"
            )


class NotebookTaskModule(ContextModule):
    """
    待办任务注入 — 让昔涟知道当前笔记本里真实的待办列表。
    防止旧对话中已完成的承诺在上下文中被误认为仍然有效。
    """

    def __init__(self):
        super().__init__(name="notebook_tasks", priority=8, max_tokens=100)
        self._notebook = None

    def set_notebook(self, nb):
        self._notebook = nb

    def render(self) -> str:
        return ""

    async def render_async(self) -> str:
        if not self._notebook:
            return ""
        try:
            lines = await self._notebook.get_pending_tasks_summary()
            if not lines:
                return ""
            tasks_text = "\n".join(lines[:4])
            return (
                "（昔涟翻开笔记本的待办页——\n"
                f"{tasks_text}\n"
                "以上就是此刻真实的待办。旧对话中的提醒如已不在列表中，说明已完成或取消，不必再提。）"
            )
        except Exception:
            return ""


# ═══════════════════════════════════════════════════════════
# ContextBuilder 协调器
# ═══════════════════════════════════════════════════════════

@dataclass
class ContextBuilder:
    """
    上下文组装器：按优先级拼装模块 → 生成自然语言段落。

    用法：
        builder = ContextBuilder(total_budget=800)
        builder.register(DatetimeModule())
        builder.register(EmotionModule(ctx))
        builder.register(MemoryModule(ctx))
        builder.register(NotebookModule())
        # ...
        notes = await builder.build()  # "（昔涟感觉到...）\\n\\n（昔涟翻到书里...）"
    """

    total_budget: int = 800
    _modules: list[ContextModule] = field(default_factory=list)

    def register(self, module: ContextModule) -> "ContextBuilder":
        self._modules.append(module)
        self._modules.sort(key=lambda m: m.priority)
        return self

    async def build(self) -> str:
        """
        按优先级+预算拼装所有模块。

        逻辑：
          remaining = total_budget
          for m in sorted modules:
              text, used = m.render_with_budget(remaining)  # 或 async 版本
              if text: parts.append(text); remaining -= used
          return parts joined with double newlines
        """
        parts: list[str] = []
        remaining = self.total_budget

        for module in self._modules:
            if not module.enabled:
                continue

            # NotebookModule / NotebookTaskModule 需要异步渲染
            if module.name in ("notebook", "notebook_tasks", "portrait_guidance"):
                text, used = await module.render_with_budget_async(remaining)
            else:
                text, used = module.render_with_budget(remaining)

            if text:
                parts.append(text)
                remaining -= used
                if remaining <= 0:
                    break

        if not parts:
            return ""

        return "\n\n".join(parts)

    def get_module(self, name: str) -> Optional[ContextModule]:
        for m in self._modules:
            if m.name == name:
                return m
        return None

    @property
    def module_names(self) -> list[str]:
        return [m.name for m in self._modules]
