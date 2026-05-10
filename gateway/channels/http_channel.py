"""
HTTPChannel — FastAPI HTTP 通道

提供 REST + SSE 接口，供前端对接。
  · POST /api/chat       同步回复
  · POST /api/chat/stream SSE 流式回复
  · GET  /api/health     健康检查
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
    ):
        super().__init__(name="HTTP")
        self.host = host
        self.port = port
        self.security = security or SecurityFilter()
        self._handler: Optional[EventHandler] = None
        self._server: Optional[uvicorn.Server] = None

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

            # 安全过滤
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
                """逐 token 推送 SSE"""
                try:
                    # 调用 Agent（stream 模式）
                    # 注意：当前 ModelRouter 的 stream 返回的是 OpenAI stream 对象
                    reply = await self._handler(filtered)
                    # 非流式兜底：整条返回
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

    # ── 启动/停止 ──

    async def start(self, handler: EventHandler) -> None:
        """启动 HTTP 服务器"""
        self._handler = handler
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",  # uvicorn 日志太吵，设 warning
        )
        self._server = uvicorn.Server(config)

        logger.info(
            "http.started",
            host=self.host,
            port=self.port,
            endpoints=["/api/chat", "/api/chat/stream", "/api/health"],
        )

        # 注意：uvicorn.Server.serve() 会阻塞当前协程
        # 在实际部署中，HTTPChannel.start() 放在 asyncio.gather 中独立运行
        await self._server.serve()

    async def send(self, text: str) -> None:
        """HTTP 通道不通过 send() 输出，响应在路由中直接返回"""
        pass

    async def stop(self) -> None:
        """关闭 HTTP 服务器"""
        if self._server:
            self._server.should_exit = True
            logger.info("http.stopped")
