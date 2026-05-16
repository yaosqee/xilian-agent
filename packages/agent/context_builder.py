"""
ContextBuilder — 模块化上下文注入系统

将上下文信息组织为独立模块，按优先级 + token 预算拼装为结构化 XML。
替代 agent_core.py 中的手工文本拼接逻辑。

阶段 7a 交付。设计见 xilian-phase7-design.md 三。
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

    每个模块独立渲染为 XML 片段，由 ContextBuilder 按优先级拼接。
    子类只需实现 render() 方法即可接入模块化系统。
    """

    name: str                              # 模块名（用于 XML tag + 日志）
    priority: int = 10                     # 越小越先分配预算（1=最高）
    max_tokens: int = 500                  # 自身硬上限
    enabled: bool = True                   # 可独立开关，调试用

    @abstractmethod
    def render(self) -> str:
        """
        渲染模块内容为纯文本。
        返回空字符串 "" 表示无内容可渲染，该模块不占位。
        """
        ...

    def render_with_budget(self, budget: int) -> tuple[str, int]:
        """
        带 token 预算渲染。

        Args:
            budget: 该模块可用的 token 上限。

        Returns:
            (xml_string, tokens_used)
        """
        content = self.render()
        if not content:
            return "", 0

        # 先用模块自身限制
        module_limit = min(budget, self.max_tokens)

        xml = f'  <module name="{self.name}">\n{content}\n  </module>'
        tokens = self._estimate_tokens(xml)

        if tokens <= module_limit:
            return xml, tokens

        # 超预算 → 按字数比例截断
        truncated = self._truncate_content(
            content,
            int(len(content) * (module_limit / max(tokens, 1))),
        )
        xml = (
            f'  <module name="{self.name}" truncated="true">\n'
            f'{truncated}\n  </module>'
        )
        return xml, module_limit

    # ── 辅助 ──

    def _estimate_tokens(self, text: str) -> int:
        """
        粗略 token 估算：UTF-8 字节 / 4。
        汉字 ~3 字节 ≈ 0.75 token，取 /4 保守。
        """
        return max(1, len(text.encode("utf-8")) // 4)

    def _truncate_content(self, content: str, max_chars: int) -> str:
        """简单按字符截断，末尾加省略号"""
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "…"


# ═══════════════════════════════════════════════════════════
# 子模块实现
# ═══════════════════════════════════════════════════════════

class DatetimeModule(ContextModule):
    """当前时间与星期（优先级最高，token 极少）"""

    def __init__(self):
        super().__init__(name="datetime", priority=1, max_tokens=60)

    def render(self) -> str:
        now = datetime.now()
        wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
        return (
            f"现在是 {now.year}年{now.month}月{now.day}日 "
            f"{now.hour:02d}:{now.minute:02d} CST，星期{wd}"
        )


class EmotionModule(ContextModule):
    """当前 PAD 情绪状态 + 快照"""

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

        # 心境映射（从 agent_core._inject_empathy 复用逻辑）
        mood_map = {
            "快乐": "心里亮亮的", "悲伤": "心有点沉", "愤怒": "心里有团火",
            "恐惧": "心里发紧", "惊讶": "心里一亮", "厌恶": "心头不悦",
            "信任": "心是安稳的", "期待": "心在轻轻跳动",
            "焦虑": "心里有一小片乌云", "平静": "心像无风的湖面",
            "兴奋": "心跳在加速",
        }
        mood = mood_map.get(primary, f"心里泛起了{primary}的涟漪")

        lines = [
            f"伙伴当下的心境：{primary}（强度 {intensity:.1f}）",
            f"人家感觉到——{mood}。",
        ]
        return "\n".join(lines)


class MemoryModule(ContextModule):
    """情景记忆检索结果"""

    def __init__(self, agent_context):
        super().__init__(name="memory", priority=5, max_tokens=300)
        self._ctx = agent_context

    def render(self) -> str:
        memories = self._ctx.memory_retrieval
        if not memories:
            return ""

        lines = []
        for i, m in enumerate(memories[:3], 1):
            summary = m.get("summary", "")
            if summary:
                lines.append(f"{i}. {summary}")

        if not lines:
            return ""

        lines.append(
            "如果这些与伙伴现在说的话有关，可以像翻到旧书页那样轻轻提起。"
        )
        return "\n".join(lines)


class NotebookModule(ContextModule):
    """
    笔记本近况 — 子阶段 7b 填充实际数据。
    当前由外部注入 notebook_manager 引用，若为 None 则静默返回空。
    """

    def __init__(self, notebook_manager=None):
        super().__init__(name="notebook", priority=6, max_tokens=250)
        self._notebook = notebook_manager

    def set_notebook(self, nb):
        """子阶段 7b 调用此方法注入 NotebookManager"""
        self._notebook = nb

    def render(self) -> str:
        if not self._notebook:
            return ""
        # 7b 暂未实现，此方法预留
        return ""


class IdentityModule(ContextModule):
    """静态身份摘要（从人格提示词提取，优先级最低）"""

    def __init__(self):
        super().__init__(name="identity", priority=9, max_tokens=60)
        self._text = "昔涟 — 三千万世轮回的记录者。自称「人家」，称用户「伙伴」。"

    def set_text(self, text: str):
        self._text = text

    def render(self) -> str:
        return self._text


# ═══════════════════════════════════════════════════════════
# ContextBuilder 协调器
# ═══════════════════════════════════════════════════════════

@dataclass
class ContextBuilder:
    """
    上下文组装器：按优先级拼装模块 → 生成结构化 XML。

    用法：
        builder = ContextBuilder(total_budget=1200)
        builder.register(DatetimeModule())
        builder.register(EmotionModule(ctx))
        # ...
        xml_text = builder.build()  # "<context>\n  <module ...>...</module>\n</context>"
    """

    total_budget: int = 1200
    _modules: list[ContextModule] = field(default_factory=list)

    def register(self, module: ContextModule) -> "ContextBuilder":
        """注册模块并保持按 priority 升序"""
        self._modules.append(module)
        self._modules.sort(key=lambda m: m.priority)
        return self

    def build(self) -> str:
        """
        按优先级+预算拼装所有模块的 XML。

        逻辑（伪代码）：
          remaining = total_budget
          for m in sorted modules:
              xml, used = m.render_with_budget(remaining)
              if xml: parts.append(xml); remaining -= used
              if remaining <= 0: break
          return wrap_in_context_tag(parts)
        """
        modules_xml: list[str] = []
        remaining = self.total_budget

        for module in self._modules:
            if not module.enabled:
                continue
            xml, used = module.render_with_budget(remaining)
            if xml:
                modules_xml.append(xml)
                remaining -= used
                if remaining <= 0:
                    break

        if not modules_xml:
            return ""

        return "<context>\n" + "\n".join(modules_xml) + "\n</context>"

    def get_module(self, name: str) -> Optional[ContextModule]:
        """按名字查找模块"""
        for m in self._modules:
            if m.name == name:
                return m
        return None

    @property
    def module_names(self) -> list[str]:
        return [m.name for m in self._modules]
