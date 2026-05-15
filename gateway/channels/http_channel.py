"""
HTTPChannel — FastAPI HTTP 通道

提供 REST + SSE 接口，供前端对接。
  · POST /api/chat           同步回复
  · POST /api/chat/stream    SSE 流式回复
  · GET  /api/health         健康检查
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
                    yield f"data: {reply}\n\n"
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
            return {"greeting": self._agent.get_time_greeting()}

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

    # ── 启动/停止 ──

    async def start(self, handler: EventHandler) -> None:
        """启动 HTTP 服务器"""
        self._handler = handler
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
                "/api/emotion", "/api/emotion/history",
                "/api/encoding-status", "/api/session/reset", "/api/status",
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
