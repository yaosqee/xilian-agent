"""模型路由观测：按模型记录成功/失败/延迟/降级。

只保留最近 N 次延迟（deque），避免长跑进程内存膨胀；
`ModelRouter.stats` 返回快照，供 /api/status 或 P3 评测读取。
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelStats:
    model_key: str
    calls: int = 0
    successes: int = 0
    errors: int = 0
    timeouts: int = 0
    empty: int = 0
    truncated: int = 0
    tool_errors: int = 0
    tool_retries: int = 0
    degraded: int = 0
    last_error: str = ""
    _latencies: deque[float] = field(default_factory=lambda: deque(maxlen=200))

    def record_call(self) -> None:
        self.calls += 1

    def record_success(self, result: Any, latency_ms: float) -> None:
        self.successes += 1
        self._latencies.append(latency_ms)
        if not hasattr(result, "content"):
            return  # raw stream / 非标准返回
        content = (getattr(result, "content", "") or "").strip()
        if not content and not getattr(result, "tool_calls", None):
            self.empty += 1
        if getattr(result, "finish_reason", None) == "length":
            self.truncated += 1

    def record_error(self, exc: BaseException, latency_ms: float) -> None:
        self.errors += 1
        self._latencies.append(latency_ms)
        self.last_error = f"{type(exc).__name__}: {exc}"[:240]
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            self.timeouts += 1

    def _percentile(self, pct: float) -> float:
        if not self._latencies:
            return 0.0
        values = sorted(self._latencies)
        index = min(len(values) - 1, max(0, int(len(values) * pct) - 1))
        return round(values[index], 1)

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "successes": self.successes,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "empty": self.empty,
            "truncated": self.truncated,
            "tool_errors": self.tool_errors,
            "tool_retries": self.tool_retries,
            "degraded": self.degraded,
            "avg_latency_ms": (
                round(sum(self._latencies) / len(self._latencies), 1)
                if self._latencies else 0.0
            ),
            "p50_latency_ms": self._percentile(0.50),
            "p95_latency_ms": self._percentile(0.95),
            "last_error": self.last_error,
        }


class ModelStatsRegistry:
    def __init__(self) -> None:
        self._stats: dict[str, ModelStats] = {}

    def get(self, model_key: str) -> ModelStats:
        if model_key not in self._stats:
            self._stats[model_key] = ModelStats(model_key=model_key)
        return self._stats[model_key]

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {key: stats.snapshot() for key, stats in self._stats.items()}

    def reset(self) -> None:
        self._stats.clear()
