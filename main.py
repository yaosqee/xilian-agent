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
from packages.agent import (
    AgentCore, NudgeEngine, TokenBucket, AutonomyConfig,
    AttentionScheduler, AttentionEvent, AttentionUrgency,
)
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

    # ── cron 辅助函数 ──
    async def _cron_loop(hour: int, minute: int, job_func, job_name: str):
        """每日在指定时间运行 job_func。"""
        import datetime
        while True:
            now = datetime.datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            wait = (target - now).total_seconds()
            logger.debug("cron.sleep", job=job_name, wait_minutes=round(wait / 60, 1))
            await asyncio.sleep(wait)
            try:
                await job_func()
            except Exception as e:
                logger.error(f"cron.{job_name}_error", error=str(e))

    # ── 阶段 5: 自传体 + 反思定时任务 ──
    async def daily_autobiography_job():
        await run_daily_autobiography(agent._db, agent.router)

    async def weekly_reflection_job():
        await run_weekly_reflection(agent._db, agent.router)

    asyncio.create_task(_cron_loop(4, 0, daily_autobiography_job, "daily_autobiography"))

    # 每周日 4:30
    async def _cron_weekly_loop(dow: int, hour: int, minute: int, job_func, job_name: str):
        """每周指定星期几运行 job_func（dow: 0=Mon, 6=Sun）。"""
        import datetime
        while True:
            now = datetime.datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # 回退到最近的指定星期几
            days_ahead = dow - target.weekday()
            if days_ahead < 0:
                days_ahead += 7
            target += datetime.timedelta(days=days_ahead)
            if target <= now:
                target += datetime.timedelta(days=7)
            wait = (target - now).total_seconds()
            logger.debug("cron.sleep", job=job_name, wait_hours=round(wait / 3600, 1))
            await asyncio.sleep(wait)
            try:
                await job_func()
            except Exception as e:
                logger.error(f"cron.{job_name}_error", error=str(e))

    asyncio.create_task(_cron_weekly_loop(6, 4, 30, weekly_reflection_job, "weekly_reflection"))
    logger.info("自传体写作调度已启动 (每日 4:00 自传体, 每周日 4:30 反思)")

    # ── 阶段 6: 自主问候 + 令牌补充调度 ──
    async def nudge_loop():
        """每 15 分钟检查一次想念值"""
        while True:
            await asyncio.sleep(900)  # 15 分钟
            try:
                decision = await nudge.tick()
                if decision.action == "greet":
                    logger.info(
                        "nudge.greeting_scheduled",
                        missing=round(nudge._current_missing_value, 2),
                        preview=decision.greeting[:60] if decision.greeting else "",
                    )
                elif decision.action == "silent":
                    logger.info("nudge.silent", reason=decision.reason)
                elif decision.action == "paused":
                    logger.info("nudge.paused", reason=decision.reason)
            except Exception as e:
                logger.error("nudge.tick_error", error=str(e))

    async def token_refill_loop():
        """每 20 分钟补充令牌"""
        while True:
            await asyncio.sleep(1200)  # 20 分钟
            try:
                nudge_bucket.refill()
            except Exception as e:
                logger.error("token_refill.error", error=str(e))

    asyncio.create_task(nudge_loop())
    asyncio.create_task(token_refill_loop())
    logger.info("自主生命节律已启动 (每15min 想念检查, 每20min 令牌补充)")

    # ── 阶段 7b: Notebook 定时任务 ──
    async def notebook_daily_diary():
        """每天 23:50 生成今日日记"""
        if agent.notebook_manager:
            diary = await agent.notebook_manager.generate_daily_diary()
            if diary:
                logger.info("notebook.diary_generated", length=len(diary))

    async def check_due_tasks():
        """每 15 分钟检查到期任务 → enqueue 到 AttentionScheduler"""
        while True:
            await asyncio.sleep(900)  # 15 分钟
            try:
                if agent.notebook_manager and agent.attention_scheduler:
                    due = await agent.notebook_manager.get_due_tasks(window_seconds=3600)
                    for task in due:
                        urgency = (
                            AttentionUrgency.IMMEDIATE if task.get("priority", 0) >= 2
                            else AttentionUrgency.SOON
                        )
                        agent.attention_scheduler.enqueue(AttentionEvent(
                            kind="task_reminder",
                            urgency=urgency,
                            payload={"task_id": task["id"], "title": task["title"]},
                        ))
                    if due:
                        logger.info("notebook.due_tasks_found", count=len(due))
            except Exception as e:
                logger.error("check_due_tasks.error", error=str(e))

    asyncio.create_task(_cron_loop(23, 50, notebook_daily_diary, "notebook_diary"))
    asyncio.create_task(check_due_tasks())
    logger.info("Notebook 调度已启动 (每日 23:50 日记, 每15分钟任务检查)")

    # ── 阶段 8+: 用户印象文档定期重写（每日凌晨 5:00，自传体之后）──
    async def consolidate_user_portrait():
        if agent.portrait_manager:
            result = await agent.portrait_manager.consolidate()
            if result:
                agent.context.user_portrait = result
                # 更新版本号（触发下次对话重新注入）
                latest = await agent._db.get_latest_portrait()
                if latest:
                    agent.context._current_portrait_version = latest.get("version", 1)
                logger.info("portrait.cron_consolidated", length=len(result))

    asyncio.create_task(_cron_loop(5, 0, consolidate_user_portrait, "portrait_consolidate"))
    logger.info("用户印象重写调度已启动 (每日 5:00)")

    # ── 阶段 7c: AttentionScheduler 初始化 ──
    attention = AttentionScheduler()
    attention._router = agent.router
    attention._db = agent._db
    attention._agent = agent
    agent.attention_scheduler = attention
    asyncio.create_task(attention.start())
    logger.info("AttentionScheduler 已启动 (5s tick)")

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

        # ── 背景图片静态挂载（photo/ 目录）──
        photo_dir = Path(__file__).parent / "photo"
        if photo_dir.exists() and photo_dir.is_dir():
            from fastapi.staticfiles import StaticFiles
            http.app.mount(
                "/photo", StaticFiles(directory=str(photo_dir)), name="photo"
            )
            logger.info(f"背景图片目录已挂载 → /photo/")

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

    # ── 5. 阶段 8: 系统托盘（Windows only）──
    tray_icon = None
    if sys.platform == "win32":
        try:
            import pystray
            from PIL import Image, ImageDraw

            # 创建简单图标（16x16 樱花色圆点）
            icon_img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
            draw = ImageDraw.Draw(icon_img)
            draw.ellipse([4, 4, 28, 28], fill=(240, 180, 200, 255))

            def on_open():
                import webbrowser
                webbrowser.open(f"http://{bind_host}:{http_port}")

            def on_pause():
                import urllib.request
                try:
                    urllib.request.urlopen(
                        urllib.request.Request(
                            f"http://{bind_host}:{http_port}/api/autonomy/pause",
                            method="POST",
                        )
                    )
                except Exception:
                    pass

            def on_exit(icon):
                icon.stop()
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda: asyncio.ensure_future(shutdown_all())
                )

            menu = pystray.Menu(
                pystray.MenuItem("打开昔涟", on_open, default=True),
                pystray.MenuItem("暂停自主行为", on_pause),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", on_exit),
            )
            tray_icon = pystray.Icon("xilian", icon_img, "昔涟", menu)
            import threading
            tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
            tray_thread.start()
            logger.info("系统托盘已启动")
        except ImportError:
            logger.info("pystray 未安装，跳过系统托盘")

    # ── 6. 启动 ──
    async def shutdown_all():
        scheduler.shutdown(wait=False)
        await gateway.stop()
        await agent.shutdown()
        if tray_icon:
            tray_icon.stop()

    try:
        await gateway.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    finally:
        scheduler.shutdown(wait=False)
        await gateway.stop()
        await agent.shutdown()
        if tray_icon:
            tray_icon.stop()
        logger.info("昔涟已休眠。晚安，伙伴 ♪")


if __name__ == "__main__":
    asyncio.run(main())
