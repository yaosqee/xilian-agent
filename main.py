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
import subprocess
import sys
import time
from pathlib import Path


def _get_base_dir() -> Path:
    """项目根目录（bundled assets）。兼容开发模式和 PyInstaller 打包模式。"""
    if getattr(sys, 'frozen', False):
        if sys._MEIPASS:
            return Path(sys._MEIPASS)
        return Path(sys.executable).parent
    return Path(__file__).parent


def _get_env_dir() -> Path:
    """.env / data 等持久化文件的目录。开发模式=项目根；打包模式=exe 所在目录。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from loguru import logger

# 确保项目根目录在 sys.path
sys.path.insert(0, str(_get_base_dir()))

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
    env_file = _get_env_dir() / ".env"
    cwd_env = Path.cwd() / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=str(env_file))
    elif cwd_env.exists():
        load_dotenv(dotenv_path=str(cwd_env))
    setup_logging()

    _frozen = getattr(sys, 'frozen', False)
    _has = bool(os.getenv("DEEPSEEK_API_KEY"))
    logger.info(
        f"env_check frozen={_frozen} has_key={_has} "
        f"env_exists={env_file.exists()} cwd_env_exists={cwd_env.exists()} "
        f"exe_dir={_get_env_dir()} cwd={Path.cwd()}"
    )

    logger.info("=" * 40)
    logger.info("昔涟 V3.2 · 心之涟漪  启动中...")
    logger.info("=" * 40)

    # ── 检查 API Key ──
    # V3.4: 检查所有已配置供应商的 API Key
    has_api_key = any(os.getenv(k) for k in (
        "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    ))
    if not has_api_key:
        logger.info("引导模式：未检测到 API Key，等待用户配置")
        await _start_onboarding()
        # 配置保存后重启进入正常模式
        logger.info("config.restarting", exe=sys.executable)
        if sys.platform == "win32":
            # Windows: shell=True 保证中文路径可用
            subprocess.Popen(
                f'"{sys.executable}"',
                shell=True,
                creationflags=0x00000008,  # DETACHED_PROCESS
            )
        else:
            subprocess.Popen([sys.executable])
        time.sleep(0.5)
        logger.info("config.exiting")
        os._exit(0)

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

    async def _backup_job():
        await backup.run_backup()
        await agent._db.set_cron_last_run("daily_backup")

    async def _cleanup_job():
        await backup.cleanup_old()
        await agent._db.set_cron_last_run("cleanup_old_backups")

    scheduler.add_job(_backup_job, trigger="cron", hour=3, minute=0, id="daily_backup")
    scheduler.add_job(_cleanup_job, trigger="cron", hour=3, minute=30, id="cleanup_old_backups")
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
                await agent._db.set_cron_last_run(job_name)
            except Exception as e:
                logger.error(f"cron.{job_name}_error", error=str(e))

    # ── 阶段 5: 自传体 + 反思定时任务 ──
    async def daily_autobiography_job():
        await run_daily_autobiography(agent._db, agent.router)

    async def weekly_reflection_job():
        await run_weekly_reflection(agent._db, agent.router)

    asyncio.create_task(_cron_loop(23, 0, daily_autobiography_job, "daily_autobiography"))

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
                await agent._db.set_cron_last_run(job_name)
            except Exception as e:
                logger.error(f"cron.{job_name}_error", error=str(e))

    asyncio.create_task(_cron_weekly_loop(6, 4, 30, weekly_reflection_job, "weekly_reflection"))
    logger.info("自传体写作调度已启动 (每日 23:00 自传体, 每周日 4:30 反思)")

    # ── 阶段 6: 自主问候 + 令牌补充调度 ──
    async def nudge_loop():
        """每 15 分钟检查一次想念值"""
        while True:
            await asyncio.sleep(900)  # 15 分钟
            # 破冰进行中 → 跳过 nudge，让破冰先完成
            if agent._icebreaker_pending or agent.context.icebreaker_active:
                logger.debug("nudge.deferred", reason="icebreaker_in_progress")
                continue
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

    # 启动时立即检查一次（不等 15 分钟）
    # 但若破冰问候待发（初次见面），跳过 nudge——避免破冰 + 想念问候同时轰炸
    if agent._icebreaker_pending:
        logger.info("nudge.startup_deferred", reason="icebreaker_pending")
    else:
        try:
            startup_decision = await nudge.tick()
            if startup_decision.action == "greet":
                logger.info(
                    "nudge.startup_greeting",
                    missing=round(nudge._current_missing_value, 2),
                    preview=startup_decision.greeting[:60] if startup_decision.greeting else "",
                )
            else:
                logger.info("nudge.startup_silent", reason=startup_decision.reason)
        except Exception as e:
            logger.error("nudge.startup_tick_error", error=str(e))

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

    asyncio.create_task(check_due_tasks())
    logger.info("Notebook 调度已启动 (每15分钟任务检查)")

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

    # ── 启动补执行：检查是否有因关机错过的定时任务 ──
    async def _catch_up_cron():
        """启动时检查并补执行错过的每日/每周定时任务。"""
        import datetime as _dt
        now = time.time()
        now_dt = _dt.datetime.fromtimestamp(now)

        # (task_name, hour, minute, is_weekly, job_func)
        tasks: list[tuple[str, int, int, bool, callable]] = [
            ("daily_backup", 3, 0, False, _backup_job),
            ("cleanup_old_backups", 3, 30, False, _cleanup_job),
            ("daily_autobiography", 23, 0, False, daily_autobiography_job),
            ("weekly_reflection", 4, 30, True, weekly_reflection_job),
            ("portrait_consolidate", 5, 0, False, consolidate_user_portrait),
        ]

        for task_name, hour, minute, is_weekly, job_func in tasks:
            last_run = await agent._db.get_cron_last_run(task_name)

            # 计算最近一次应触发的时间
            target = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if is_weekly:
                target -= _dt.timedelta(days=(target.weekday() - 6) % 7)
            if target > now_dt:
                target -= _dt.timedelta(days=7 if is_weekly else 1)

            if last_run is None:
                # 首次运行：记录当前时间，不补执行
                await agent._db.set_cron_last_run(task_name, now)
                continue

            # 如果应触发时间晚于上次执行时间，说明错过了
            if target.timestamp() > last_run:
                logger.info("cron.catch_up", task=task_name, missed=target.isoformat())
                try:
                    await job_func()
                    await agent._db.set_cron_last_run(task_name)
                    logger.info("cron.catch_up_done", task=task_name)
                except Exception as e:
                    logger.error("cron.catch_up_error", task=task_name, error=str(e))

    # 等 agent 完全就绪后再补执行（让 scheduler 先跑起来）
    asyncio.create_task(_catch_up_cron())

    # ── 阶段 7c: AttentionScheduler 初始化 ──
    attention = AttentionScheduler()
    attention._router = agent.router
    attention._db = agent._db
    attention._agent = agent
    attention._nudge_engine = nudge  # 桥接：notify → pending_greeting
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
        photo_dir = _get_base_dir() / "photo"
        if photo_dir.exists() and photo_dir.is_dir():
            from fastapi.staticfiles import StaticFiles
            http.app.mount(
                "/photo", StaticFiles(directory=str(photo_dir)), name="photo"
            )
            logger.info(f"背景图片目录已挂载 → /photo/")

        # ── 阶段 6: 前端嵌入后端（生产模式）──
        frontend_dist = _get_base_dir() / "packages" / "frontend" / "dist"
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

    # ── 5. 阶段 8: 系统托盘 ──
    tray_icon = None
    try:
        import pystray
        from PIL import Image

        # 加载托盘图标（优先 .ico，其次 .png，最后用代码生成）
        base = _get_base_dir()
        icon_path = None
        for candidate in [
            base / "photo" / "tray_icon.ico",
            base / "photo" / "tray_icon.png",
        ]:
            if candidate.exists():
                icon_path = candidate
                break

        if icon_path:
            icon_img = Image.open(str(icon_path))
        else:
            # 兜底：代码生成简单樱花色图标
            from PIL import ImageDraw
            icon_img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
            draw = ImageDraw.Draw(icon_img)
            draw.ellipse([4, 4, 28, 28], fill=(255, 183, 197, 255))

        def on_open():
            import webbrowser
            webbrowser.open(f"http://{bind_host}:{http_port}")

        def on_pause():
            try:
                import urllib.request
                urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://{bind_host}:{http_port}/api/autonomy/pause",
                        method="POST",
                    )
                )
            except Exception:
                pass

        def on_exit(tray_icon_ref):
            tray_icon_ref.stop()
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
        logger.info("系统托盘已启动", icon="file" if icon_path else "generated")
    except ImportError:
        logger.info("pystray 未安装，跳过系统托盘")
    except Exception as e:
        logger.warning("tray.init_failed", error=str(e))

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


async def _start_onboarding():
    """引导模式：仅启动 HTTP 服务 + 静态文件，等待用户配置 API Key。
    配置保存后通过 asyncio.Event 通知，优雅关闭服务器，然后由 main() 重启进程。"""
    security = SecurityFilter(owner_id="hezi")

    http_port = int(os.getenv("HTTP_PORT", "8000"))
    bind_host = os.getenv("BIND_HOST", "127.0.0.1")

    http = HTTPChannel(host=bind_host, port=http_port, security=security, agent=None)

    from fastapi import Request
    from fastapi.responses import JSONResponse

    _done = asyncio.Event()

    @http.app.post("/api/config/save")
    async def save_config(request: Request):
        body = await request.json()
        # 新增：支持多供应商选择（V3.4+）
        provider = (body.get("provider") or "deepseek").strip()
        api_key = (body.get("deepseek_key") or body.get("api_key") or "").strip()
        siliconflow_key = (body.get("siliconflow_key") or "").strip()

        if not api_key:
            return JSONResponse({"status": "error", "message": "API Key 不能为空"}, status_code=400)

        # Provider → env var mapping
        env_var_map = {
            "deepseek": "DEEPSEEK_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        target_env_var = env_var_map.get(provider, "DEEPSEEK_API_KEY")

        env_path = _get_env_dir() / ".env"
        env_lines: list[str] = []
        if env_path.exists():
            env_lines = env_path.read_text(encoding="utf-8").splitlines()

        updated_main = False
        updated_embed = False
        for i, line in enumerate(env_lines):
            if line.startswith(f"{target_env_var}="):
                env_lines[i] = f"{target_env_var}={api_key}"
                updated_main = True
            elif line.startswith("EMBED_API_KEY=") and siliconflow_key:
                env_lines[i] = f"EMBED_API_KEY={siliconflow_key}"
                updated_embed = True

        if not updated_main:
            env_lines.append(f"{target_env_var}={api_key}")
        if siliconflow_key and not updated_embed:
            env_lines.append(f"EMBED_API_KEY={siliconflow_key}")
        if siliconflow_key:
            has_base_url = any(l.startswith("EMBED_BASE_URL=") for l in env_lines)
            if not has_base_url:
                env_lines.append("EMBED_BASE_URL=https://api.siliconflow.cn/v1")

        content = "\n".join(env_lines) + "\n"
        env_path.write_text(content, encoding="utf-8")
        logger.info("config.saved",
            env_path=str(env_path),
            provider=provider,
            wrote_bytes=len(content),
            verify_exists=env_path.exists(),
            verify_size=env_path.stat().st_size if env_path.exists() else -1,
        )

        os.environ[target_env_var] = api_key
        if siliconflow_key:
            os.environ["EMBED_API_KEY"] = siliconflow_key

        _done.set()
        return {"status": "ok", "message": "配置已保存", "provider": provider}

    @http.app.get("/api/config/debug")
    async def debug_config():
        env_dir = _get_env_dir()
        env_path = env_dir / ".env"
        return {
            "frozen": getattr(sys, 'frozen', False),
            "sys_executable": sys.executable,
            "env_dir": str(env_dir),
            "env_path": str(env_path),
            "env_exists": env_path.exists(),
            "cwd": str(Path.cwd()),
        }

    @http.app.get("/api/config/check")
    async def check_config():
        # V3.4+: 检查任意供应商的 API Key
        has_key = bool(
            os.getenv("DEEPSEEK_API_KEY") or
            os.getenv("OPENAI_API_KEY") or
            os.getenv("ANTHROPIC_API_KEY") or
            os.getenv("GOOGLE_API_KEY")
        )
        return {"has_api_key": has_key}

    # 静态文件挂载
    base = _get_base_dir()
    photo_dir = base / "photo"
    if photo_dir.exists() and photo_dir.is_dir():
        from fastapi.staticfiles import StaticFiles
        http.app.mount("/photo", StaticFiles(directory=str(photo_dir)), name="photo")

    frontend_dist = base / "packages" / "frontend" / "dist"
    if frontend_dist.exists() and os.getenv("FRONTEND_DEV", "").lower() not in ("1", "true"):
        from fastapi.staticfiles import StaticFiles
        http.app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
        logger.info(f"引导模式 → http://{bind_host}:{http_port}")
    else:
        logger.info(f"引导模式（开发） → http://localhost:5173")

    # 启动 HTTP 服务，等待配置完成信号后优雅关闭
    config_obj = uvicorn.Config(http.app, host=bind_host, port=http_port, log_level="warning")
    server = uvicorn.Server(config_obj)

    async def _serve_until_done():
        server_task = asyncio.create_task(server.serve())
        await _done.wait()
        logger.info("config.done, shutting down onboarding server")
        server.should_exit = True
        await server_task

    try:
        await _serve_until_done()
    except KeyboardInterrupt:
        logger.info("引导模式中断")


if __name__ == "__main__":
    asyncio.run(main())
