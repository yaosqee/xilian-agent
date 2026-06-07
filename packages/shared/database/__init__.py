"""
Database 包 — 领域 Repository + DatabaseManager 委托层

外部调用方通过 from packages.shared.database import DatabaseManager 导入，
行为与拆分前完全一致（DatabaseManager 公开 API 不变）。
"""

from ._manager import DatabaseManager

__all__ = ["DatabaseManager"]
