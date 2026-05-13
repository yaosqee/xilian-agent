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

        # ── 阶段 3 新增端点 ──

        @self.app.get("/api/emotion")
        async def get_emotion():
            """获取当前情绪快照"""
            if self._agent is None:
                return {"error": "agent not available"}
            snap = self._agent.context.emotion_snapshot
            if not snap:
                return {"emotion": None, "message": "暂无情绪数据"}
            return {"emotion": snap}

        @self.app.get("/api/emotion/history")
        async def get_emotion_history(limit: int = 50):
            """获取情绪历史记录"""
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                history = await self._agent._db.get_emotion_history(limit=limit)
                return {"history": history, "count": len(history)}
            except Exception as e:
                logger.warning("api.emotion_history_failed", error=str(e))
                return {"history": [], "error": str(e)}

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
            chroma_ok = False
            try:
                memory_count = await self._agent._db.get_episodic_count()
            except Exception:
                pass
            try:
                chroma_ok = await self._agent.memory_manager.health_check()
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
                "chroma_ok": chroma_ok,
                "encoding_state": self._agent.memory_manager.encoding_state,
            }

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
