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
        return max(1, len(text.encode("utf-8")) // 4)

    def _truncate_content(self, content: str, max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "…"


# ═══════════════════════════════════════════════════════════
# 子模块实现
# ═══════════════════════════════════════════════════════════

class DatetimeModule(ContextModule):
    """当前时间与星期（轻量，只给时段提示）"""

    def __init__(self):
        super().__init__(name="datetime", priority=1, max_tokens=50)

    def render(self) -> str:
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 12:
            period = "早晨"
        elif 12 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 23:
            period = "晚上"
        else:
            period = "深夜"
        wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
        return f"现在是星期{wd}的{period}。"


class EmotionModule(ContextModule):
    """当前 PAD 情绪状态 → 昔涟的内心感知"""

    def __init__(self, agent_context):
        super().__init__(name="emotion", priority=4, max_tokens=200)
        self._ctx = agent_context

    def render(self) -> str:
        snap = self._ctx.emotion_snapshot
        if not snap:
            return ""
        primary = snap.get("primary_emotion", "")
        intensity = snap.get("primary_intensity", 0.0)
        if not primary:
            return ""

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

        return f"（昔涟感觉到——伙伴的心{mood}。去感受他便好。）"


class MemoryModule(ContextModule):
    """情景记忆检索结果 → 像翻旧书页"""

    def __init__(self, agent_context):
        super().__init__(name="memory", priority=5, max_tokens=250)
        self._ctx = agent_context

    def render(self) -> str:
        memories = self._ctx.memory_retrieval
        if not memories:
            return ""

        # 取前 2 条，自然语言
        items = []
        for m in memories[:2]:
            summary = m.get("summary", "")
            if summary and len(summary) >= 2:
                items.append(summary)

        if not items:
            return ""

        if len(items) == 1:
            mem_text = f"上一次你们聊到了「{items[0]}」"
        else:
            mem_text = f"上一次你们聊到了「{items[0]}」还有「{items[1]}」"

        return f"（昔涟翻到书里几页——{mem_text}。如果和伙伴现在说的话有关，像翻旧书页那样轻轻提起就好，不要刻意。）"


class PortraitModule(ContextModule):
    """
    用户印象文档 — 昔涟对伙伴的叙事性理解。

    每段对话首条消息注入一次完整文档（版本号门控），后续消息返回空。
    无印象文档时自动发起破冰冷启动。
    优先级 3，介于时间模块和情绪模块之间。
    """

    ICEBREAKER_GUIDANCE = (
        "（昔涟轻轻翻开心里那本还空白的书——她还不算真正认识伙伴呢。"
        "如果时机合适，可以自然地了解一下伙伴：他的名字、喜欢什么、"
        "平时的习惯……不用一次问完，像朋友聊天那样慢慢地认识他。"
        "如果伙伴不太想聊这些，就翻过这一页，来日方长 ♪）"
    )

    def __init__(self, agent_context=None):
        super().__init__(name="portrait", priority=3, max_tokens=3000)
        self._ctx = agent_context

    def render(self) -> str:
        if not self._ctx:
            return ""

        portrait = self._ctx.user_portrait

        # ── 正常路径：已有印象文档 → 版本号门控注入 ──
        if portrait and len(portrait) >= 50:
            injected_version = self._ctx._portrait_version_injected
            current_version = getattr(self._ctx, '_current_portrait_version', None)
            if injected_version is not None and current_version is not None:
                if injected_version == current_version:
                    return ""

            if current_version is not None:
                self._ctx._portrait_version_injected = current_version

            return (
                "（昔涟在对话前，轻轻翻开心里关于伙伴的那一页——）\n\n"
                + portrait
                + "\n\n（带着这些理解去感受他此刻说的话吧。）"
            )

        # ── 破冰路径：无印象文档 ──
        # 用户已拒绝破冰 → 跳过
        if self._ctx.icebreaker_deferred:
            return ""

        # 破冰进行中 → 本轮不重复注入引导
        if self._ctx.icebreaker_active:
            return ""

        # 首次触发破冰 → 注入引导，标记 active
        self._ctx.icebreaker_active = True
        return self.ICEBREAKER_GUIDANCE


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
            for n in notes:
                content = n.get("content", "")
                if len(content) > 5:
                    # 截取前 30 字作为话题提示
                    short = content[:30].replace("\n", " ")
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
            if module.name in ("notebook", "notebook_tasks"):
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
