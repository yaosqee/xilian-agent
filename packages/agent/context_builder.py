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
            "快乐": "心里亮亮的，像有阳光洒在书页上",
            "悲伤": "心有点沉，像雨滴落在水面",
            "愤怒": "心里有一小团火在跳",
            "恐惧": "心里发紧，像风吹过空荡的走廊",
            "惊讶": "心里一亮，像忽然翻到一本没读过的书",
            "厌恶": "心头不太舒服，像吃到了一颗酸果子",
            "信任": "心是安稳的，像靠着秋千的绳子",
            "期待": "心在轻轻跳动，像种子在土里翻身",
            "焦虑": "心里有一小片乌云飘来飘去",
            "平静": "心像无风的湖面，安安静静的",
            "兴奋": "心跳在加速，像流星划过的瞬间",
        }
        mood = mood_map.get(primary, f"心里泛起了{primary}的涟漪")

        return f"（昔涟感觉到——伙伴的心{intensity * 100:.0f}分地{primary}。{mood}。不必刻意分析他的情绪，去感受他便好。）"


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

            # NotebookModule 需要异步渲染
            if module.name == "notebook":
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
