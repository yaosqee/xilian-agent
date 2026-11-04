"""模型能力策略（ModelPolicy）。

把「某模型知不知道怎么调工具 / 看不看得懂图 / 上下文多大 / 贵不贵」
从 `ModelRouter` 的异常缓存里拆出来，变成显式、可查询、可配置的事实。

当前数据源优先 adapter 的 `get_available_models() -> ModelInfo`；
找不到时退回 adapter 自身的能力布尔值。后续若把模型配置迁到 DB / DSH 风格，
只需要在 `ModelPolicy` 这一层接配置，不用再改路由主流程。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .base import ModelInfo


@dataclass(frozen=True)
class ModelPolicy:
    """一个具体模型的显式能力与成本。"""

    provider: str
    model: str

    supports_tools: bool = True
    supports_vision: bool = False
    supports_streaming: bool = True
    supports_thinking: bool = False

    context_window: int = 128_000
    max_output_tokens: int = 8_000

    cost_per_1k_in: float = 0.0
    cost_per_1k_out: float = 0.0

    # 未来可放已知失败模式（如 "tool_choice": "thinking"），当前保留扩展位
    known_failures: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"

    @classmethod
    def from_model_info(cls, info: ModelInfo, provider: str) -> "ModelPolicy":
        return cls(
            provider=provider,
            model=info.id,
            supports_tools=bool(info.supports_tools),
            supports_vision="image" in (info.input_modalities or []),
            supports_streaming=bool(info.supports_streaming),
            supports_thinking=bool(info.supports_thinking),
            context_window=int(info.context_window),
            max_output_tokens=int(info.max_output_tokens),
            cost_per_1k_in=float(info.cost_per_1k_in),
            cost_per_1k_out=float(info.cost_per_1k_out),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["key"] = self.key
        return data


def policy_from_adapter(adapter: Any, provider: str, model: str) -> ModelPolicy:
    """从 adapter 的模型元数据构建策略；找不到具体模型时用 adapter 能力兜底。"""
    try:
        for info in adapter.get_available_models():
            if model in (info.id, info.name):
                return ModelPolicy.from_model_info(info, provider)
    except Exception:
        pass

    return ModelPolicy(
        provider=provider,
        model=model,
        supports_tools=bool(getattr(adapter, "supports_tools", True)),
        supports_vision=False,
        supports_streaming=bool(getattr(adapter, "supports_streaming", True)),
        supports_thinking=bool(getattr(adapter, "supports_thinking", False)),
    )
