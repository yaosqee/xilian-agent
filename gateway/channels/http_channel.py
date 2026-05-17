"""
HTTPChannel — FastAPI HTTP 通道

提供 REST + SSE 接口，供前端对接。
  · POST /api/chat           同步回复
  · POST /api/chat/stream    SSE 流式回复
  · GET  /api/health         健康检查
  · GET  /api/conversation/history 对话历史分页
  · GET  /api/emotion        当前情绪快照（阶段 3 新增）
  · GET  /api/emotion/history 情绪历史（阶段 3 新增）
  · GET  /api/encoding-status 记忆编码状态（阶段 3 新增）
  · POST /api/session/reset   重置会话（阶段 3 新增）
  · GET  /api/status          系统状态摘要（阶段 3 新增）
"""
import asyncio
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn
from loguru import logger

from .base import Channel, EventHandler
from packages.shared.events import InternalEvent
from gateway.security import SecurityFilter


class HTTPChannel(Channel):
    """FastAPI 通道，提供 HTTP + SSE 接口"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        security: Optional[SecurityFilter] = None,
        agent=None,  # AgentCore 引用（阶段 3 新增端点用）
    ):
        super().__init__(name="HTTP")
        self.host = host
        self.port = port
        self.security = security or SecurityFilter()
        self._handler: Optional[EventHandler] = None
        self._server: Optional[uvicorn.Server] = None
        self._agent = agent  # AgentCore 引用
        self._nudge_engine = None  # 阶段 6: NudgeEngine 引用

        # 构建 FastAPI 应用
        self.app = FastAPI(title="昔涟 V3.2 API", version="0.1.0")
        self._setup_middleware()
        self._setup_routes()

    # ── 中间件 ──

    def _setup_middleware(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://localhost:3000"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── 路由 ──

    def _setup_routes(self):
        """注册 HTTP 端点"""
        agent = self  # 闭包引用

        @self.app.get("/api/health")
        async def health():
            return {"status": "ok", "service": "xilian-v3"}

        @self.app.post("/api/chat")
        async def chat(request: Request):
            """同步回复"""
            body = await request.json()
            user_msg = body.get("message", "")
            user_id = body.get("user_id", "anonymous")
            stream = body.get("stream", False)

            if not user_msg.strip():
                return {"error": "empty message"}

            event = InternalEvent(
                source="http",
                user_id=user_id,
                payload=user_msg,
                is_owner=(user_id == self.security.owner_id),
            )

            filtered = self.security.filter(event)
            if filtered is None:
                return {"error": "blocked"}

            if self._handler is None:
                return {"error": "agent not ready"}

            reply = await self._handler(filtered)
            return {"reply": reply}

        @self.app.post("/api/chat/stream")
        async def chat_stream(request: Request):
            """SSE 流式回复"""
            body = await request.json()
            user_msg = body.get("message", "")
            user_id = body.get("user_id", "anonymous")

            if not user_msg.strip():
                return {"error": "empty message"}

            event = InternalEvent(
                source="http",
                user_id=user_id,
                payload=user_msg,
                is_owner=(user_id == self.security.owner_id),
            )

            filtered = self.security.filter(event)
            if filtered is None:
                return {"error": "blocked"}

            if self._handler is None:
                return {"error": "agent not ready"}

            async def sse_generator():
                try:
                    reply = await self._handler(filtered)
                    # 逐块流式推送（模拟打字效果，3字符/块，50ms间隔）
                    chunk_size = 3
                    for i in range(0, len(reply), chunk_size):
                        chunk = reply[i:i+chunk_size]
                        # SSE 格式需要转义换行符
                        safe = chunk.replace("\n", "\\n")
                        yield f"data: {safe}\n\n"
                        await asyncio.sleep(0.05)
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    logger.error("sse.error", error=str(e))
                    yield f"data: 人家走神了呢……伙伴再试一次好不好？\n\n"
                    yield "data: [DONE]\n\n"

            return StreamingResponse(
                sse_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # ── 对话历史 ──

        @self.app.get("/api/conversation/history")
        async def conversation_history(before_id: int | None = None, limit: int = 10):
            """游标分页查询历史对话。首次不传 before_id 取最新，后续传 oldest_id 向前翻页。"""
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                limit = min(limit, 20)
                rows = await self._agent._db.get_conversation_history(
                    before_id=before_id, limit=limit,
                )
                total = await self._agent._db.get_conversation_total()
                # DB 返回 DESC → 逆转为 ASC 给前端
                items = [{
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "user_message": row["user_message"],
                    "assistant_reply": row["assistant_reply"],
                } for row in reversed(rows)]
                return {
                    "items": items,
                    "total": total,
                    "has_more": len(rows) >= limit,
                    "oldest_id": rows[-1]["id"] if rows else None,
                }
            except Exception as e:
                logger.warning("api.conversation_history_failed", error=str(e))
                return {"items": [], "total": 0, "has_more": False, "oldest_id": None, "error": str(e)}

        # ── 阶段 3-4 情感端点 ──

        @self.app.get("/api/emotion")
        async def get_emotion():
            """获取当前情绪快照（PAD + 11维 + 标签）"""
            if self._agent is None:
                return {"error": "agent not available"}
            if not hasattr(self._agent, 'emotion_engine') or self._agent.emotion_engine is None:
                return {"emotion": None, "message": "情感引擎未初始化"}

            engine = self._agent.emotion_engine
            # 先衰减再返回（反映当前时刻的真实状态）
            engine.state.decay()
            profile = engine.state.compute_profile()
            state_dict = engine.state.to_dict()
            state_dict["since_last_update_seconds"] = round(time.time() - engine.state.timestamp, 1)
            return state_dict

        @self.app.get("/api/emotion/history")
        async def get_emotion_history(limit: int = 50, offset: int = 0):
            """获取 PAD 轨迹历史"""
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                snapshots = await self._agent._db.get_emotion_snapshots(
                    limit=min(limit, 200), offset=offset
                )
                # 计算统计
                stats = {}
                if snapshots:
                    pads = [(s["pad_p"], s["pad_a"], s["pad_d"]) for s in snapshots]
                    n = len(pads)
                    stats["avg_p"] = round(sum(p[0] for p in pads) / n, 4)
                    stats["avg_a"] = round(sum(p[1] for p in pads) / n, 4)
                    stats["avg_d"] = round(sum(p[2] for p in pads) / n, 4)
                    # 主情绪统计
                    from collections import Counter
                    emotions = [s["primary_emotion"] for s in snapshots if s.get("primary_emotion")]
                    stats["dominant_emotion"] = Counter(emotions).most_common(1)[0][0] if emotions else None

                return {
                    "snapshots": [{
                        "timestamp": s["timestamp"],
                        "pad": {"P": s["pad_p"], "A": s["pad_a"], "D": s["pad_d"]},
                        "primary_emotion": s.get("primary_emotion"),
                    } for s in snapshots],
                    "stats": stats,
                    "count": len(snapshots),
                }
            except Exception as e:
                logger.warning("api.emotion_history_failed", error=str(e))
                return {"snapshots": [], "error": str(e)}

        @self.app.get("/api/emotion/stats")
        async def get_emotion_stats(days: int = 7):
            """获取情绪统计周报"""
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                stats = await self._agent._db.get_emotion_stats(days=min(days, 30))
                return stats
            except Exception as e:
                logger.warning("api.emotion_stats_failed", error=str(e))
                return {"error": str(e)}

        # ── 阶段 5 新增端点 ──

        @self.app.get("/api/memories/recent")
        async def get_memories_recent(limit: int = 20):
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                memories = await self._agent._db.get_episodic_recent(limit=min(limit, 50))
                return {
                    "memories": [{
                        "id": m["id"],
                        "summary": m.get("summary", "")[:200],
                        "timestamp": m.get("timestamp"),
                        "importance": m.get("importance", 0.5),
                        "emotion_tags": m.get("emotion_tags"),
                        "access_count": m.get("access_count", 0),
                    } for m in memories],
                    "count": len(memories),
                }
            except Exception as e:
                return {"memories": [], "error": str(e)}

        @self.app.get("/api/autobiography")
        async def get_autobiography(date: str | None = None):
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                entry = await self._agent._db.get_autobiography(date)
                if entry:
                    return {"entry": {"date": entry["date"], "content": entry["content"],
                                     "mood_summary": entry.get("mood_summary"), "word_count": entry.get("word_count", 0)}}
                return {"entry": None}
            except Exception as e:
                return {"error": str(e)}

        @self.app.get("/api/autobiography/list")
        async def get_autobiography_list(limit: int = 30):
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                entries = await self._agent._db.get_autobiography_list(limit=min(limit, 100))
                return {"entries": entries, "count": len(entries)}
            except Exception as e:
                return {"entries": [], "error": str(e)}

        @self.app.get("/api/reflection/latest")
        async def get_reflection_latest():
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                r = await self._agent._db.get_latest_reflection()
                if r:
                    return {"reflection": {"week_start": r["week_start"], "week_end": r["week_end"],
                        "learned": r.get("learned"), "surprised": r.get("surprised"),
                        "grateful": r.get("grateful"), "remember": r.get("remember")}}
                return {"reflection": None}
            except Exception as e:
                return {"error": str(e)}

        @self.app.get("/api/greeting")
        async def get_greeting():
            if self._agent is None:
                return {"error": "agent not available"}
            icebreaker = self._agent.consume_icebreaker_greeting()
            if icebreaker:
                return {"greeting": icebreaker, "is_first_meeting": True}
            return {"greeting": self._agent.get_time_greeting()}

        # ── 用户印象文档 ──
        @self.app.get("/api/user/portrait")
        async def get_user_portrait():
            """获取昔涟对伙伴的当前印象文档。"""
            _agent = self._agent
            if not _agent or not _agent._db:
                return {"portrait": None, "version": 0}
            try:
                portrait = await _agent._db.get_latest_portrait()
                if not portrait:
                    return {"portrait": None, "version": 0}
                return {
                    "portrait": portrait["content"],
                    "version": portrait["version"],
                    "updated_at": portrait["created_at"],
                    "changes": portrait.get("change_log", ""),
                }
            except Exception as e:
                logger.warning("api.portrait_failed", error=str(e))
                return {"error": str(e)}

        # ── 好感度 ──
        @self.app.get("/api/affection")
        async def get_affection():
            _agent = self._agent
            if not _agent or not _agent._db:
                return {"error": "agent not available"}
            try:
                latest = await _agent._db.get_latest_affection()
                level_labels = {
                    1: "昔涟喜欢你",
                    2: "昔涟非常喜欢你",
                    3: "昔涟特别喜欢你",
                    4: "你永远喜欢昔涟",
                }
                if not latest:
                    return {
                        "score": 0.0,
                        "level": 1,
                        "level_label": level_labels[1],
                        "total_conversations": 0,
                    }
                score = latest["score"]
                level = latest["level"]
                return {
                    "score": score,
                    "level": level,
                    "level_label": level_labels.get(level, level_labels[1]),
                    "total_conversations": latest["total_conversations"],
                    "updated_at": latest["updated_at"],
                }
            except Exception as e:
                logger.warning("api.affection_failed", error=str(e))
                return {"error": str(e)}

        @self.app.get("/api/encoding-status")
        async def get_encoding_status():
            """获取记忆编码状态"""
            if self._agent is None:
                return {"error": "agent not available"}
            mm = self._agent.memory_manager
            return {
                "state": mm.encoding_state,
                "has_pending": mm.has_pending_encoding,
            }

        @self.app.post("/api/session/reset")
        async def reset_session():
            """重置当前会话"""
            if self._agent is None:
                return {"error": "agent not available"}
            self._agent.reset_session()
            logger.info("api.session_reset")
            return {"status": "ok", "message": "会话已重置"}

        @self.app.get("/api/status")
        async def get_status():
            """获取系统状态摘要"""
            if self._agent is None:
                return {"error": "agent not available"}

            memory_count = 0
            vec_ok = False
            try:
                memory_count = await self._agent._db.get_episodic_count()
            except Exception:
                pass
            try:
                vec_ok = await self._agent.memory_manager.health_check()
            except Exception:
                pass

            return {
                "service": "xilian-v3",
                "version": "0.1.0",
                "phase": 3,
                "session_id": self._agent._db.session_id,
                "history_size": len(self._agent.context.history),
                "emotion_available": self._agent.context.emotion_snapshot is not None,
                "memory_count": memory_count,
                "vec_ok": vec_ok,
                "encoding_state": self._agent.memory_manager.encoding_state,
            }

    # ── 阶段 6: NudgeEngine 注入 ──

    def set_nudge_engine(self, nudge_engine) -> None:
        """注入 NudgeEngine 实例（供 /api/autonomy/* 端点使用）"""
        self._nudge_engine = nudge_engine
        self._register_autonomy_routes()
        logger.info("http.nudge_engine_injected")

    def _register_autonomy_routes(self):
        """注册自主行为 API 端点（在 set_nudge_engine 调用后注册）"""
        nudge = self  # 闭包引用

        @self.app.get("/api/autonomy/status")
        async def autonomy_status():
            """获取自主行为状态"""
            if nudge._nudge_engine is None:
                return {"error": "nudge engine not initialized"}
            return nudge._nudge_engine.status

        @self.app.post("/api/autonomy/pause")
        async def autonomy_pause():
            """暂停所有自主行为"""
            if nudge._nudge_engine is None:
                return {"error": "nudge engine not initialized"}
            nudge._nudge_engine.pause()
            # 持久化
            try:
                await nudge._agent._db.save_autonomy_config(
                    nudge._nudge_engine._config.to_dict()
                )
            except Exception as e:
                logger.warning("autonomy.config_save_failed", error=str(e))
            return {"status": "paused"}

        @self.app.post("/api/autonomy/resume")
        async def autonomy_resume():
            """恢复自主行为"""
            if nudge._nudge_engine is None:
                return {"error": "nudge engine not initialized"}
            nudge._nudge_engine.resume()
            try:
                await nudge._agent._db.save_autonomy_config(
                    nudge._nudge_engine._config.to_dict()
                )
            except Exception as e:
                logger.warning("autonomy.config_save_failed", error=str(e))
            return {"status": "resumed"}

        @self.app.patch("/api/autonomy/settings")
        async def autonomy_settings(request: Request):
            """更新自主行为配置"""
            if nudge._nudge_engine is None:
                return {"error": "nudge engine not initialized"}
            body = await request.json()
            allowed = [
                "greeting_enabled", "greeting_threshold", "greeting_max_per_hour",
                "greeting_active_start", "greeting_active_end",
                "do_not_disturb", "dnd_start", "dnd_end",
            ]
            patch = {k: v for k, v in body.items() if k in allowed}
            if not patch:
                return {"error": "no valid settings provided"}
            config = nudge._nudge_engine.update_config(patch)
            # 持久化
            try:
                await nudge._agent._db.save_autonomy_config(config.to_dict())
            except Exception as e:
                logger.warning("autonomy.config_save_failed", error=str(e))
            return {"status": "ok", "config": config.to_dict()}

        @self.app.get("/api/autonomy/pending-greeting")
        async def pending_greeting():
            """获取待展示的主动问候"""
            if nudge._nudge_engine is None:
                return {"has_greeting": False, "greeting": None, "id": None}
            return nudge._nudge_engine.get_pending_greeting()

        @self.app.post("/api/autonomy/ack-greeting")
        async def ack_greeting(request: Request):
            """确认收到问候"""
            if nudge._nudge_engine is None:
                return {"error": "nudge engine not initialized"}
            body = await request.json()
            greeting_id = body.get("id", "")
            if not greeting_id:
                return {"error": "missing greeting id"}
            ok = nudge._nudge_engine.ack_greeting(greeting_id)
            return {"status": "ok" if ok else "id_mismatch"}

    # ── 背景图片 API ──

    def _register_background_routes(self):
        """注册背景图片 API 端点。"""
        import json
        import uuid
        from pathlib import Path
        from fastapi import UploadFile, File

        photo_dir = Path(__file__).resolve().parent.parent.parent / "photo"
        config_path = photo_dir / "background_config.json"

        def _read_config():
            if config_path.exists():
                try:
                    return json.loads(config_path.read_text())
                except Exception:
                    pass
            return {"active": "xilian.png"}

        def _write_config(cfg: dict):
            config_path.write_text(json.dumps(cfg, ensure_ascii=False))

        @self.app.get("/api/background/current")
        async def background_current():
            cfg = _read_config()
            active = cfg.get("active", "xilian.png")
            return {"filename": active, "url": f"/photo/{active}"}

        @self.app.post("/api/background/upload")
        async def background_upload(file: UploadFile = File(...)):
            if not file.content_type or not file.content_type.startswith("image/"):
                return {"error": "仅支持图片文件"}
            # 限制 10MB
            contents = await file.read()
            if len(contents) > 10 * 1024 * 1024:
                return {"error": "图片大小不能超过 10MB"}
            # 保留扩展名
            ext = Path(file.filename).suffix if file.filename else ".png"
            if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                ext = ".png"
            filename = f"custom_{uuid.uuid4().hex[:8]}{ext}"
            save_path = photo_dir / filename
            save_path.write_bytes(contents)
            # 设为活跃背景
            _write_config({"active": filename})
            logger.info("background.uploaded", filename=filename)
            return {"filename": filename, "url": f"/photo/{filename}"}

    # ── 阶段 7b: Notebook API ──

    def _register_notebook_routes(self):
        """注册 Notebook API 端点（在 AgentCore 就绪后调用）。"""
        agent = self._agent

        @self.app.get("/api/notebook/notes")
        async def notebook_notes(limit: int = 10):
            """获取最近笔记"""
            if not agent or not agent.notebook_manager:
                return []
            items = await agent.notebook_manager.get_recent_notes(limit)
            return items

        @self.app.get("/api/notebook/diary")
        async def notebook_diary(date: str | None = None):
            """获取指定日期或今日日记"""
            if not agent or not agent.notebook_manager:
                return {"error": "notebook not available"}
            return await agent.notebook_manager.get_today_diary()

        @self.app.get("/api/notebook/diary/list")
        async def notebook_diary_list(limit: int = 30):
            """获取日记列表"""
            if not agent or not agent.notebook_manager:
                return []
            return await agent.notebook_manager.get_diary_list(limit)

        @self.app.get("/api/notebook/tasks")
        async def notebook_tasks(status: str = "pending"):
            """获取任务列表"""
            if not agent or not agent.notebook_manager:
                return []
            if status == "pending":
                return await agent.notebook_manager.get_pending_tasks()
            return []

        @self.app.post("/api/notebook/tasks/{task_id}/complete")
        async def notebook_task_complete(task_id: int):
            """标记任务完成"""
            if not agent or not agent.notebook_manager:
                return {"error": "notebook not available"}
            await agent.notebook_manager.complete_task(task_id)
            return {"status": "ok"}

        @self.app.post("/api/notebook/tasks/{task_id}/cancel")
        async def notebook_task_cancel(task_id: int):
            """取消任务"""
            if not agent or not agent.notebook_manager:
                return {"error": "notebook not available"}
            await agent.notebook_manager.cancel_task(task_id)
            return {"status": "ok"}

    # ── 阶段 8: 审计 + 技能 + 安全状态 API ──

    def _register_stage8_routes(self):
        """注册阶段 8 管理面板 API 端点。"""
        agent = self._agent

        # ── 审计日志 ──
        @self.app.get("/api/audit/logs")
        async def audit_logs(
            limit: int = 50, event_type: str | None = None,
            severity: str | None = None,
        ):
            if not agent or not agent._db:
                return []
            return await agent._db.get_audit_logs(
                limit=limit, event_type=event_type, severity=severity,
            )

        @self.app.get("/api/audit/stats")
        async def audit_stats():
            if not agent or not agent._db:
                return {"total": 0, "by_type": {}}
            return await agent._db.get_audit_stats()

        # ── 技能管理 ──
        @self.app.get("/api/skills")
        async def skills_list():
            if not agent or not hasattr(agent, '_skills_loader'):
                return {"skills": {}}
            from packages.agent.skills_loader import SkillsLoader
            loader = SkillsLoader()
            loader.load_all()
            result = {}
            for name, s in loader.skills.items():
                result[name] = {
                    "category": s.category,
                    "description": s.description,
                    "triggers": s.triggers,
                    "safety": s.safety,
                    "version": s.version,
                }
            return {"skills": result}

        # ── 安全状态 ──
        @self.app.get("/api/security/status")
        async def security_status():
            if not agent:
                return {"error": "agent not available"}
            return {
                "safe_mode": agent.is_safe_mode,
                "round_count": agent._round_count,
            }


        # ── 被遗忘权 ──
        @self.app.post("/api/privacy/forget")
        async def privacy_forget(request: Request):
            """级联删除用户数据（需二次确认）。"""
            if not agent or not agent._db:
                return {"error": "agent not available"}
            try:
                body = await request.json()
            except Exception:
                return {"error": "invalid json"}
            confirm = body.get("confirm", "")
            if confirm != "我确认删除所有记忆":
                return {"error": "请输入确认短语「我确认删除所有记忆」"}
            result = await agent._db.forget_user_data()
            return {"status": "ok", **result}

    # ── 启动/停止 ──

    async def start(self, handler: EventHandler) -> None:
        """启动 HTTP 服务器"""
        self._handler = handler

        # 背景图片 API
        self._register_background_routes()

        # 阶段 7b: 注册 Notebook API
        if self._agent and self._agent.notebook_manager:
            self._register_notebook_routes()

        # 阶段 8: 注册审计 + 技能 + 安全状态 API
        if self._agent and self._agent._db:
            self._register_stage8_routes()

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        logger.info(
            "http.started",
            host=self.host,
            port=self.port,
            endpoints=[
                "/api/chat", "/api/chat/stream", "/api/health",
                "/api/conversation/history",
                "/api/emotion", "/api/emotion/history",
                "/api/encoding-status", "/api/session/reset", "/api/status",
                "/api/notebook/*",
            ],
        )

        await self._server.serve()

    async def send(self, text: str) -> None:
        """HTTP 通道不通过 send() 输出"""
        pass

    async def stop(self) -> None:
        """关闭 HTTP 服务器"""
        if self._server:
            self._server.should_exit = True
            logger.info("http.stopped")
