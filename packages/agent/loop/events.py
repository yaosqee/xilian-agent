"""
Agent 循环 v2 事件协议 + 结构化工具结果。

P0 只有数据结构，不接 SSE / 前端。事件名与
`docs/plans/agent-loop-v2.md` §2.3 对齐：

    tool_call   -> ToolCallEvent
    tool_result -> ToolResultEvent
    token       -> TokenEvent（P1 真流式时由 runner 产出）
    done        -> DoneEvent

设计要点：
- 工具调用先归一化成 `ToolCall`，解析失败也不抛异常，而是带 `argument_error` 交给执行器；
- 工具结果统一成 `ToolOutcome`，回填给模型的 content 固定为
  `{"ok": true, "data": ...}` / `{"ok": false, "error": ...}`；
- 所有事件都能 `to_dict()` / `to_sse()`，后续接传输层不用改结构。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, TypeAlias


def _json_default(value: Any) -> str:
    """SSE 序列化兜底：不可 JSON 化的值转字符串，避免整条事件丢失。"""
    return str(value)


@dataclass
class LoopEvent:
    """所有循环事件的基类（只提供序列化辅助，不持有字段）。"""

    type: ClassVar[str] = "event"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type
        return data

    def to_sse(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, default=_json_default)
        return f"event: {self.type}\ndata: {payload}\n\n"


# ─────────────────────────────────────────────────────────────
# 工具调用
# ─────────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """归一化后的工具调用。

    `raw_arguments` 保留模型返回的原始 JSON 字符串（回填 assistant 消息时原样写回，
    保证多步对话与模型上下文一致）；`arguments` 是解析后的 dict。
    解析失败时 `arguments` 为空 dict，`argument_error` 说明原因，执行器会直接判失败，
    不会带病调用工具。
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = "{}"
    argument_error: str = ""

    @classmethod
    def from_raw(cls, raw: Any, *, index: int = 0) -> "ToolCall":
        """把 OpenAI 格式的 tool_call（dict 或对象）归一化。

        兼容两种输入：
        - dict: {"id": ..., "function": {"name": ..., "arguments": "{...}"}}
        - 对象: 带 .id / .function.name / .function.arguments 属性
        """
        if isinstance(raw, dict):
            call_id = str(raw.get("id") or f"call_{index}")
            function = raw.get("function") or {}
            name = str(function.get("name") or "") if isinstance(function, dict) else ""
            raw_arguments = function.get("arguments") if isinstance(function, dict) else None
        else:
            call_id = str(getattr(raw, "id", "") or f"call_{index}")
            function = getattr(raw, "function", None)
            name = str(getattr(function, "name", "") or "") if function is not None else ""
            raw_arguments = getattr(function, "arguments", None) if function is not None else None

        if isinstance(raw_arguments, dict):
            arguments = dict(raw_arguments)
            raw_str = json.dumps(arguments, ensure_ascii=False, default=str)
            return cls(id=call_id, name=name, arguments=arguments, raw_arguments=raw_str)

        if isinstance(raw_arguments, str) and raw_arguments.strip():
            raw_str = raw_arguments
            try:
                parsed = json.loads(raw_arguments)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return cls(
                    id=call_id,
                    name=name,
                    arguments={},
                    raw_arguments=raw_str,
                    argument_error=f"工具「{name or '?'}」的参数不是合法 JSON：{exc}",
                )
            if not isinstance(parsed, dict):
                return cls(
                    id=call_id,
                    name=name,
                    arguments={},
                    raw_arguments=raw_str,
                    argument_error=f"工具「{name or '?'}」的参数必须是 JSON 对象",
                )
            return cls(id=call_id, name=name, arguments=parsed, raw_arguments=raw_str)

        # 空参数 / None -> {}
        return cls(id=call_id, name=name, arguments={}, raw_arguments="{}")


# ─────────────────────────────────────────────────────────────
# 工具结果（结构化）
# ─────────────────────────────────────────────────────────────


@dataclass
class ToolOutcome:
    """单个工具调用的结构化结果。

    这是新循环的边界类型：执行器只产出它，runner 只消费它。
    `content()` 就是回填到 `{"role": "tool"}` 消息里的字符串。
    """

    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    data: Any = None
    error: str = ""
    cached: bool = False          # True = 本轮幂等缓存命中，没有真正执行
    duration_ms: int = 0
    needs_confirmation: bool = False  # 工具要求用户确认，循环应停下
    # 从 ToolResult 透传的副作用标记，供 AgentCore 接线后复用原有逻辑
    trigger_memory: bool = False
    trigger_portrait_update: bool = False

    def structured(self) -> dict[str, Any]:
        """回填给模型的结构化载荷。"""
        if self.ok:
            payload: dict[str, Any] = {"ok": True, "data": self.data}
        else:
            payload = {"ok": False, "error": self.error or "工具执行失败"}
        if self.cached:
            payload["cached"] = True
        if self.needs_confirmation:
            payload["needs_confirmation"] = True
        return payload

    def content(self) -> str:
        """tool 消息的 content（JSON 字符串，不夹带人格改写）。"""
        return json.dumps(self.structured(), ensure_ascii=False, default=_json_default)


# ─────────────────────────────────────────────────────────────
# 事件
# ─────────────────────────────────────────────────────────────


@dataclass
class ToolCallEvent(LoopEvent):
    """模型在本步请求执行工具（此时尚未执行）。"""

    type: ClassVar[str] = "tool_call"
    step: int = 1
    calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ToolResultEvent(LoopEvent):
    """本步工具执行完毕（并行执行后一次性产出）。"""

    type: ClassVar[str] = "tool_result"
    step: int = 1
    results: list[ToolOutcome] = field(default_factory=list)


@dataclass
class TokenEvent(LoopEvent):
    """增量文本。runner 在 stream=True 时实时产出。"""

    type: ClassVar[str] = "token"
    text: str = ""
    step: int = 0


@dataclass
class DoneEvent(LoopEvent):
    """循环结束。

    reason 取值：
    - stop           模型给出最终文本
    - empty          模型既没有文本也没有工具调用（空回复，由上层决定降级话术）
    - max_steps      步数预算耗尽
    - budget_tokens  总 token 预算耗尽
    - budget_time    总耗时预算耗尽
    - confirmation   工具要求确认，循环暂停
    - error          模型调用异常
    """

    type: ClassVar[str] = "done"
    text: str = ""
    reason: str = "stop"
    steps: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    error: str = ""
    # confirmation 暂停时挂起的调用 + 恢复用上下文（assistant + 已执行工具消息）
    pending: list[ToolCall] = field(default_factory=list)
    resume_messages: list[dict] = field(default_factory=list)


LoopEventType: TypeAlias = ToolCallEvent | ToolResultEvent | TokenEvent | DoneEvent
