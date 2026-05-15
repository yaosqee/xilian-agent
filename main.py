"""
昔涟 V3.3 · 启动入口

启动流程：
  1. setup_logging()          结构化日志
  2. AgentCore 初始化 + startup DB初始化 + 记忆模块启动
  3. NudgeEngine 初始化        自主生命节律（阶段 6）
  4. BackupManager 初始化     每日凌晨 3:00 备份
  5. Gateway 初始化            注册 ConsoleChannel + HTTPChannel
  6. 通道并发启动              终端对话 + HTTP API 同时运行
"""
import asyncio
import os
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from loguru import logger

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from packages.shared import ModelRouter, BackupManager
from packages.shared.logging_config import setup_logging
from packages.agent import AgentCore, NudgeEngine, TokenBucket, AutonomyConfig
from packages.agent.autobiography_writer import run_daily_autobiography, run_weekly_reflection
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

    # ── 阶段 6: NudgeEngine 初始化 ──
    nudge_bucket = TokenBucket()
    # 从 DB 加载已有配置，否则用默认
    saved_config = await agent._db.get_autonomy_config()
    nudge_config = AutonomyConfig.from_dict(saved_config) if saved_config else AutonomyConfig()
    nudge = NudgeEngine(
        db=agent._db,
        model_router=agent.router,
        token_bucket=nudge_bucket,
        config=nudge_config,
    )
    logger.info("nudge_engine.ready", config=nudge_config.to_dict())

    # ── 2. 备份管理器 + 定时调度 ──
    backup = BackupManager(
        db_path="data/xilian.db",
        backup_root="backups",
        keep_days=7,
    )
    scheduler = AsyncIOScheduler()
    scheduler.add_job(backup.run_backup, trigger="cron", hour=3, minute=0, id="daily_backup")
    scheduler.add_job(backup.cleanup_old, trigger="cron", hour=3, minute=30, id="cleanup_old_backups")
    scheduler.start()
    logger.info("备份调度已启动 (每日 3:00 备份, 3:30 清理)")

    # ── 阶段 5: 自传体 + 反思定时任务 ──
    scheduler.add_job(
        lambda: asyncio.create_task(run_daily_autobiography(agent._db, agent.router)),
        trigger="cron", hour=4, minute=0, id="daily_autobiography",
    )
    scheduler.add_job(
        lambda: asyncio.create_task(run_weekly_reflection(agent._db, agent.router)),
        trigger="cron", day_of_week="sun", hour=4, minute=30, id="weekly_reflection",
    )
    logger.info("自传体写作调度已启动 (每日 4:00 自传体, 每周日 4:30 反思)")

    # ── 阶段 6: 自主问候 + 令牌补充调度 ──
    async def nudge_tick():
        decision = await nudge.tick()
        if decision.action == "greet":
            logger.info(
                "nudge.greeting_scheduled",
                missing=round(nudge._current_missing_value, 2),
                preview=decision.greeting[:60] if decision.greeting else "",
            )
        elif decision.action == "silent":
            logger.debug("nudge.silent", reason=decision.reason)

    scheduler.add_job(
        lambda: asyncio.create_task(nudge_tick()),
        trigger="interval", minutes=15, id="proactive_check",
    )
    scheduler.add_job(
        nudge_bucket.refill,
        trigger="interval", minutes=20, id="token_bucket_refill",
    )
    logger.info("自主生命节律调度已启动 (每15min 想念检查, 每20min 令牌补充)")

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
        bind_host = os.getenv("BIND_HOST", "127.0.0.1")
        http = HTTPChannel(host=bind_host, port=http_port, security=security, agent=agent)
        gateway.register(http)

        # ── 阶段 6: NudgeEngine 注入 HTTPChannel（供 /api/autonomy/*）──
        http.set_nudge_engine(nudge)

        # ── 阶段 6: 前端嵌入后端（生产模式）──
        frontend_dist = Path(__file__).parent / "packages" / "frontend" / "dist"
        if frontend_dist.exists() and os.getenv("FRONTEND_DEV", "").lower() not in ("1", "true"):
            from fastapi.staticfiles import StaticFiles
            http.app.mount(
                "/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend"
            )
            logger.info(f"前端已嵌入（生产模式）→ http://{bind_host}:{http_port}")
        else:
            logger.info(f"前端开发模式 → http://localhost:5173")

        # 局域网提示
        if bind_host == "0.0.0.0":
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                logger.info(f"局域网访问地址 → http://{local_ip}:{http_port}")
            except Exception:
                pass

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
