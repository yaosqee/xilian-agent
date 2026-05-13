"""
昔涟 V3.2 · 启动入口

启动流程：
  1. setup_logging()          结构化日志
  2. AgentCore 初始化 + startup DB初始化 + 记忆模块启动
  3. BackupManager 初始化     每日凌晨 3:00 备份
  4. Gateway 初始化            注册 ConsoleChannel + HTTPChannel
  5. 通道并发启动              终端对话 + HTTP API 同时运行
"""
import asyncio
import os
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from loguru import logger

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from packages.shared import ModelRouter, BackupManager
from packages.shared.logging_config import setup_logging
from packages.agent import AgentCore
from gateway import Gateway, SecurityFilter
from gateway.channels import ConsoleChannel, HTTPChannel


async def main():
    # ── 0. 加载环境 ──
    load_dotenv()
    setup_logging()

    logger.info("=" * 40)
    logger.info("昔涟 V3.2 · 心之涟漪  启动中...")
    logger.info("=" * 40)

    # ── 1. Agent 核心初始化 ──
    agent = AgentCore()
    await agent.startup()  # 阶段 3: DB 初始化 + 记忆模块启动

    # ── 2. 备份管理器 + 定时调度 ──
    backup = BackupManager(
        db_path="data/xilian.db",
        chroma_path="chroma_data",
        backup_root="backups",
        keep_days=7,
    )
    scheduler = AsyncIOScheduler()
    scheduler.add_job(backup.run_backup, trigger="cron", hour=3, minute=0, id="daily_backup")
    scheduler.add_job(backup.cleanup_old, trigger="cron", hour=3, minute=30, id="cleanup_old_backups")
    scheduler.start()
    logger.info("备份调度已启动 (每日 3:00 备份, 3:30 清理)")

    # ── 3. 安全过滤层 ──
    security = SecurityFilter(owner_id="hezi")

    # ── 4. 网关 + 通道注册 ──
    gateway = Gateway(agent, security)

    # Console 通道：终端交互（默认启用）
    console = ConsoleChannel(security)
    gateway.register(console)

    # HTTP 通道：FastAPI API（可通过环境变量禁用）
    if os.getenv("NO_HTTP", "").lower() not in ("1", "true", "yes"):
        http_port = int(os.getenv("HTTP_PORT", "8000"))
        http = HTTPChannel(host="127.0.0.1", port=http_port, security=security, agent=agent)
        gateway.register(http)

    # ── 5. 启动 ──
    try:
        await gateway.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    finally:
        scheduler.shutdown(wait=False)
        await gateway.stop()
        await agent.shutdown()  # 阶段 3: 记忆兜底 + DB 关闭
        logger.info("昔涟已休眠。晚安，伙伴 ♪")


if __name__ == "__main__":
    asyncio.run(main())
