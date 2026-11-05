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
import inspect
import json
import os
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


# ── Agent 循环 v2 事件 → SSE ────────────────────────────────


def _summarize_tool_data(data, limit: int = 120) -> str:
    """把工具结果压成一行给前端气泡，避免整块 JSON 塞进 UI。"""
    if data is None:
        return ""
    if isinstance(data, dict):
        parts = []
        for value in data.values():
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple)):
                value = "、".join(str(item) for item in value[:3])
            parts.append(str(value))
        text = "，".join(parts) if parts else json.dumps(data, ensure_ascii=False)
    elif isinstance(data, (list, tuple)):
        text = "、".join(str(item) for item in data[:3])
    else:
        text = str(data)
    return " ".join(text.split())[:limit]


def _format_token_frame(text: str) -> str:
    """Token 帧。SSE 的 data 不能含未转义换行，和原假流式保持一致。"""
    safe = text.replace("\n", "\\n")
    return f"event: token\ndata: {safe}\n\n"


def _format_loop_event(loop_event) -> str | None:
    """把 ToolCallEvent / ToolResultEvent / TokenEvent 转成 SSE 帧。"""
    from packages.agent.loop.events import TokenEvent, ToolCallEvent, ToolResultEvent

    if isinstance(loop_event, TokenEvent):
        if not loop_event.text:
            return None
        return _format_token_frame(loop_event.text)

    if isinstance(loop_event, ToolCallEvent):
        payload = {
            "step": loop_event.step,
            "calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in loop_event.calls
            ],
        }
        return f"event: tool_call\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    if isinstance(loop_event, ToolResultEvent):
        payload = {
            "step": loop_event.step,
            "results": [
                {
                    "name": outcome.name,
                    "ok": outcome.ok,
                    "cached": outcome.cached,
                    "needs_confirmation": outcome.needs_confirmation,
                    "summary": _summarize_tool_data(outcome.data) if outcome.ok else "",
                    "error": (
                        "" if outcome.ok or outcome.needs_confirmation
                        else outcome.error
                    ),
                }
                for outcome in loop_event.results
            ],
        }
        return f"event: tool_result\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return None


def _handler_accepts_event_sink(handler) -> bool:
    """判断 handler 是否支持 event_sink（AgentCore.process 支持，老 handler 不支持）。"""
    try:
        return "event_sink" in inspect.signature(handler).parameters
    except (TypeError, ValueError):
        return False


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
        # 注册 Notebook + 审计/技能 + 背景图片 + 多模态路由（提前到 __init__，确保 FastAPI 路由生效）
        self._register_background_routes()
        self._register_notebook_routes()
        self._register_stage8_routes()
        self._register_model_routes()
        self._register_multimodal_routes()

    # ── 中间件 ──

    def _setup_middleware(self):
        import socket

        # 基础来源：开发模式
        origins = [
            f"http://localhost:{self.port}",
            "http://localhost:5173",
            "http://localhost:3000",
        ]

        # 从环境变量解析额外来源
        extra = os.getenv("CORS_ORIGINS", "")
        if extra:
            origins.extend(o.strip() for o in extra.split(",") if o.strip())

        # 如果绑定 0.0.0.0，自动添加检测到的局域网 IP
        lan_ip = None
        if self.host == "0.0.0.0":
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
                s.close()
                origins.append(f"http://{lan_ip}:{self.port}")
                origins.append(f"http://{lan_ip}:5173")  # 开发模式
            except Exception:
                pass

        # 同时允许私有网络来源（应对多网卡 / Docker 虚拟网卡等场景）
        # 匹配 192.168.x.x, 10.x.x.x, 172.16-31.x.x，可选端口
        private_net_regex = (
            r"^https?://("
            r"(localhost|127\.0\.0\.1)(:\d+)?"
            r"|(192\.168\.\d+\.\d+)(:\d+)?"
            r"|(10\.\d+\.\d+\.\d+)(:\d+)?"
            r"|(172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?"
            r")$"
        )

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_origin_regex=private_net_regex,
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

        @self.app.get("/api/lan-info")
        async def lan_info():
            """返回局域网连接信息，供手机扫描二维码"""
            import socket

            result = {
                "host": self.host,
                "port": self.port,
                "lan_url": None,
                "lan_ip": None,
            }
            if self.host == "0.0.0.0":
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    lan_ip = s.getsockname()[0]
                    s.close()
                    result["lan_ip"] = lan_ip
                    result["lan_url"] = f"http://{lan_ip}:{self.port}"
                except Exception:
                    pass
            return result

        @self.app.post("/api/chat")
        async def chat(request: Request):
            """同步回复"""
            body = await request.json()
            user_msg = body.get("message", "")
            user_id = body.get("user_id", "anonymous")
            session_id = body.get("session_id", "default")
            images = body.get("images", []) or []

            if not user_msg.strip() and not images:
                return {"error": "empty message"}

            event = InternalEvent(
                source="http",
                user_id=user_id,
                session_id=session_id,
                payload=user_msg,
                images=images,
                is_owner=(user_id == self.security.owner_id),
            )

            filtered = self.security.filter(event)
            if filtered is None:
                return {"error": "blocked"}

            if self._handler is None:
                return {"error": "agent not ready"}

            # 更新自主问候回退时间戳
            if self._nudge_engine:
                self._nudge_engine.poke()

            response = await self._handler(filtered)
            return {"reply": response.reply, "sticker": response.sticker}

        @self.app.post("/api/chat/stream")
        async def chat_stream(request: Request):
            """SSE 流式回复"""
            body = await request.json()
            user_msg = body.get("message", "")
            user_id = body.get("user_id", "anonymous")
            session_id = body.get("session_id", "default")
            images = body.get("images", []) or []

            if not user_msg.strip() and not images:
                return {"error": "empty message"}

            event = InternalEvent(
                source="http",
                user_id=user_id,
                session_id=session_id,
                payload=user_msg,
                images=images,
                is_owner=(user_id == self.security.owner_id),
            )

            filtered = self.security.filter(event)
            if filtered is None:
                return {"error": "blocked"}

            if self._handler is None:
                return {"error": "agent not ready"}

            # 更新自主问候回退时间戳
            if self._nudge_engine:
                self._nudge_engine.poke()

            async def sse_generator():
                from packages.agent.loop.events import TokenEvent
                from packages.shared.marker_parser import MarkerParser

                queue: asyncio.Queue = asyncio.Queue()
                sentinel = object()
                # 真 token 流：标记（sticker/emotion/…）在服务端过滤，只把可见文本推给前端。
                marker_parser = MarkerParser()
                streamed_chars = 0

                async def event_sink(loop_event):
                    nonlocal streamed_chars
                    if isinstance(loop_event, TokenEvent):
                        for token in marker_parser.feed(loop_event.text):
                            if token.kind == "literal" and token.text:
                                streamed_chars += len(token.text.strip())
                                await queue.put(_format_token_frame(token.text))
                        return

                    chunk = _format_loop_event(loop_event)
                    if chunk:
                        await queue.put(chunk)

                async def run_handler():
                    try:
                        if _handler_accepts_event_sink(self._handler):
                            return await self._handler(filtered, event_sink=event_sink)
                        return await self._handler(filtered)
                    finally:
                        await queue.put(sentinel)

                task = asyncio.create_task(run_handler())
                try:
                    # 先把工具阶段事件按发生顺序吐出去（LOOP_V2 才有）
                    while True:
                        item = await queue.get()
                        if item is sentinel:
                            break
                        yield item

                    # 流结束时把 MarkerParser 里剩的普通文本吐完（例如未闭合的 [）
                    for token in marker_parser.flush():
                        if token.kind == "literal" and token.text:
                            streamed_chars += len(token.text.strip())
                            yield _format_token_frame(token.text)

                    response = await task
                    reply = response.reply
                    sticker = getattr(response, "sticker", None)

                    # 先发送 sticker 事件（如果有）
                    if sticker:
                        yield f"event: sticker\ndata: {json.dumps(sticker, ensure_ascii=False)}\n\n"

                    # 真 token 流已经推过正文 → 不再重复假切片
                    chunk_size = 3
                    for i in range(0, len(reply) if streamed_chars == 0 else 0, chunk_size):
                        chunk = reply[i:i+chunk_size]
                        # SSE 格式需要转义换行符
                        safe = chunk.replace("\n", "\\n")
                        yield f"event: token\ndata: {safe}\n\n"
                        await asyncio.sleep(0.05)
                    yield "event: done\ndata: [DONE]\n\n"
                except Exception as e:
                    logger.error("sse.error", error=str(e))
                    yield "event: token\ndata: 人家走神了呢……伙伴再试一次好不好？\n\n"
                    yield "event: done\ndata: [DONE]\n\n"
                finally:
                    if not task.done():
                        task.cancel()

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
                    "images": json.loads(row["images"]) if row["images"] else [],
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
                        "summary": m.get("summary", ""),
                        "raw_conversation": m.get("raw_conversation", ""),
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

        @self.app.post("/api/autobiography/generate")
        async def generate_autobiography():
            """手动触发今日自传体生成（无需等待凌晨4点 cron）。"""
            if self._agent is None:
                return {"error": "agent not available"}
            try:
                from packages.agent.autobiography_writer import AutobiographyWriter
                import datetime
                writer = AutobiographyWriter(self._agent._db, self._agent.router)
                date_str = datetime.datetime.now().strftime("%Y-%m-%d")
                content = await writer.write_daily(date_str)
                if content:
                    from loguru import logger
                    logger.info("api.autobiography_generated", date=date_str, chars=len(content))
                    return {"status": "ok", "date": date_str, "content": content}
                return {"status": "skipped", "reason": "no new conversations today"}
            except Exception as e:
                return {"error": str(e)}

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
            """获取昔涟对伙伴的分层印象文档（L0 核心画像 + L1 阶段画像）。"""
            _agent = self._agent
            if not _agent or not _agent._db:
                return {"portrait": None, "version": 0}
            try:
                # L0 核心画像
                l0 = await _agent._db.get_latest_core_profile()
                # L1 阶段画像
                l1 = await _agent._db.get_latest_phase_profile()

                # 构建返回（保留旧字段兼容）
                result: dict = {
                    "portrait": None,
                    "version": 0,
                    "updated_at": None,
                    "changes": "",
                }

                # L0 数据
                if l0 and l0.get("content"):
                    result["portrait"] = l0["content"]
                    result["version"] = l0.get("version", 0)
                    result["updated_at"] = l0.get("created_at")
                    result["changes"] = l0.get("change_log", "") or ""
                    result["stable_traits"] = l0.get("stable_traits", "") or ""

                # L1 数据
                if l1 and l1.get("content"):
                    result["phase_portrait"] = l1["content"]
                    result["phase_version"] = l1.get("version", 0)
                    result["phase_updated_at"] = l1.get("created_at")
                    result["phase_changes"] = l1.get("change_log", "") or ""
                    import json
                    try:
                        result["active_topics"] = json.loads(l1.get("active_topics", "[]") or "[]")
                    except (json.JSONDecodeError, TypeError):
                        result["active_topics"] = []
                    try:
                        result["faded_topics"] = json.loads(l1.get("faded_topics", "[]") or "[]")
                    except (json.JSONDecodeError, TypeError):
                        result["faded_topics"] = []

                # 无分层数据时回退旧 user_portrait
                if not result["portrait"]:
                    old = await _agent._db.get_latest_portrait()
                    if old and old.get("content"):
                        result["portrait"] = old["content"]
                        result["version"] = old.get("version", 0)
                        result["updated_at"] = old.get("created_at")
                        result["changes"] = old.get("change_log", "") or ""

                return result
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
            await self._agent.reset_session()
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
                "loop_v2": bool(getattr(self._agent, "_loop_v2", False)),
                "intent_router": bool(getattr(self._agent, "_intent_router", True)),
                "routing_v2": bool(getattr(self._agent.router, "routing_v2", False)),
                "model_stats": (
                    self._agent.router.stats
                    if hasattr(self._agent.router, "stats") else {}
                ),
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
            return await nudge._nudge_engine.status()

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
        """注册 Notebook API 端点。通过 self 动态访问 _agent，避免闭包过期。"""
        http = self  # 引用 HTTPChannel 实例，运行时动态取 _agent

        @self.app.get("/api/notebook/notes")
        async def notebook_notes(limit: int = 10):
            """获取最近笔记"""
            if not http._agent or not http._agent.notebook_manager:
                return []
            items = await http._agent.notebook_manager.get_recent_notes(limit)
            return items

        @self.app.get("/api/notebook/tasks")
        async def notebook_tasks(status: str = "pending"):
            """获取任务列表"""
            if not http._agent or not http._agent.notebook_manager:
                return []
            if status == "pending":
                return await http._agent.notebook_manager.get_pending_tasks()
            return []

        @self.app.post("/api/notebook/tasks/{task_id}/complete")
        async def notebook_task_complete(task_id: int):
            """标记任务完成"""
            if not http._agent or not http._agent.notebook_manager:
                return {"error": "notebook not available"}
            await http._agent.notebook_manager.complete_task(task_id)
            return {"status": "ok"}

        @self.app.post("/api/notebook/tasks/{task_id}/cancel")
        async def notebook_task_cancel(task_id: int):
            """取消任务"""
            if not http._agent or not http._agent.notebook_manager:
                return {"error": "notebook not available"}
            await http._agent.notebook_manager.cancel_task(task_id)
            return {"status": "ok"}

        @self.app.delete("/api/notebook/notes/{note_id}")
        async def notebook_note_delete(note_id: int):
            """删除笔记"""
            if not http._agent or not http._agent.notebook_manager:
                return {"error": "notebook not available"}
            ok = await http._agent.notebook_manager.delete_note(note_id)
            if ok:
                return {"status": "ok"}
            return {"status": "not_found"}

        @self.app.delete("/api/notebook/tasks/{task_id}")
        async def notebook_task_delete(task_id: int):
            """删除任务"""
            if not http._agent or not http._agent.notebook_manager:
                return {"error": "notebook not available"}
            ok = await http._agent.notebook_manager.delete_task(task_id)
            if ok:
                return {"status": "ok"}
            return {"status": "not_found"}

    # ── 阶段 8: 审计 + 技能 + 安全状态 API ──

    def _register_stage8_routes(self):
        """注册阶段 8 管理面板 API 端点。通过 self 动态访问 _agent。"""
        http = self

        # ── 审计日志 ──
        @self.app.get("/api/audit/logs")
        async def audit_logs(
            limit: int = 50, event_type: str | None = None,
            severity: str | None = None,
        ):
            if not http._agent or not http._agent._db:
                return []
            return await http._agent._db.get_audit_logs(
                limit=limit, event_type=event_type, severity=severity,
            )

        @self.app.get("/api/audit/stats")
        async def audit_stats():
            if not http._agent or not http._agent._db:
                return {"total": 0, "by_type": {}}
            return await http._agent._db.get_audit_stats()

        # ── 技能管理 ──
        @self.app.get("/api/skills")
        async def skills_list():
            if not http._agent or not http._agent._skills_loader:
                return {"skills": {}}
            result = {}
            for name, s in http._agent._skills_loader.skills.items():
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
            if not http._agent:
                return {"error": "http._agent not available"}
            return {
                "safe_mode": http._agent.is_safe_mode,
                "round_count": http._agent._round_count,
            }


        # ── 被遗忘权 ──
        @self.app.post("/api/privacy/forget")
        async def privacy_forget(request: Request):
            """级联删除用户数据（需二次确认）。"""
            if not http._agent or not http._agent._db:
                return {"error": "http._agent not available"}
            try:
                body = await request.json()
            except Exception:
                return {"error": "invalid json"}
            confirm = body.get("confirm", "")
            if confirm != "我确认删除所有记忆":
                return {"error": "请输入确认短语「我确认删除所有记忆」"}
            result = await http._agent._db.forget_user_data()
            return {"status": "ok", **result}

    # ── 多模态 + 表情包 API ──

    def _register_multimodal_routes(self):
        """注册图片上传 + 表情包 API 端点。"""
        import uuid as _uuid
        import json as _json
        from pathlib import Path as _Path
        from fastapi import UploadFile, File
        from fastapi.responses import FileResponse

        # 上传目录
        uploads_dir = _Path(__file__).resolve().parent.parent.parent / "data" / "uploads"
        stickers_dir = _Path(__file__).resolve().parent.parent.parent / "data" / "stickers"

        @self.app.post("/api/upload")
        async def upload_image(file: UploadFile = File(...)):
            """上传图片（供聊天多模态使用）"""
            if not file.content_type or not file.content_type.startswith("image/"):
                return {"error": "仅支持图片文件"}
            contents = await file.read()
            max_size = 10 * 1024 * 1024  # 10MB
            if len(contents) > max_size:
                return {"error": "图片大小不能超过 10MB"}

            ext = _Path(file.filename).suffix if file.filename else ".png"
            if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                ext = ".webp"

            from datetime import datetime
            month_dir = datetime.now().strftime("%Y-%m")
            dest = uploads_dir / month_dir
            dest.mkdir(parents=True, exist_ok=True)

            img_id = _uuid.uuid4().hex[:12]
            filename = f"{img_id}{ext}"
            save_path = dest / filename
            save_path.write_bytes(contents)

            stored_path = f"{month_dir}/{filename}"
            url = f"/api/uploads/{stored_path}"

            # 写入数据库
            if self._agent and self._agent._db:
                try:
                    await self._agent._db.insert_image(
                        image_id=img_id,
                        user_id="hezi",
                        original_name=file.filename or "",
                        stored_path=stored_path,
                        mime_type=file.content_type or "",
                        size_bytes=len(contents),
                    )
                except Exception as e:
                    logger.warning("upload.insert_db_failed", error=str(e))

            logger.info("upload.image_ok", id=img_id, name=file.filename, size=len(contents))
            return {"id": img_id, "url": url}

        @self.app.get("/api/stickers")
        async def get_stickers():
            """返回可用表情包列表"""
            catalog_path = stickers_dir / "catalog.json"
            if catalog_path.exists():
                try:
                    return _json.loads(catalog_path.read_text())
                except Exception:
                    pass
            return {"stickers": [], "version": 0}

        # 静态文件路由：上传的图片和表情包
        @self.app.get("/api/uploads/{file_path:path}")
        async def serve_upload(file_path: str):
            fp = uploads_dir / file_path
            # 安全检查：确保路径在 uploads_dir 内
            try:
                fp.resolve().relative_to(uploads_dir.resolve())
            except ValueError:
                return {"error": "invalid path"}
            if fp.exists():
                return FileResponse(str(fp))
            return {"error": "not found"}

        @self.app.get("/api/stickers/{file_path:path}")
        async def serve_sticker(file_path: str):
            fp = stickers_dir / file_path
            try:
                fp.resolve().relative_to(stickers_dir.resolve())
            except ValueError:
                return {"error": "invalid path"}
            if fp.exists():
                return FileResponse(str(fp))
            return {"error": "not found"}

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
                "/api/conversation/history",
                "/api/emotion", "/api/emotion/history",
                "/api/encoding-status", "/api/session/reset", "/api/status",
                "/api/notebook/*",
            ],
        )

        await self._server.serve()

    # ── 模型配置 API（Phase B: 多供应商路由）──

    def _register_model_routes(self):
        """注册模型配置管理端点。通过 self 动态访问 _agent。"""
        http = self

        # ── 可用供应商和模型列表（动态从 PROVIDER_REGISTRY 生成）──
        @self.app.get("/api/models/providers")
        async def model_providers():
            """动态从各 adapter 的 get_available_models() 生成供应商列表。

            遍历 PROVIDER_REGISTRY，排除专用 adapter（如 MiMo），
            通过静态方法获取模型列表，无需实例化 adapter。
            DB 已添加的供应商/模型会覆盖静态列表，并标记连接状态。
            """
            from packages.shared.providers import PROVIDER_REGISTRY
            import importlib

            # 仅面向用户的对话供应商（排除内部专用 adapter）
            CHAT_PROVIDERS = {"deepseek", "openai", "anthropic", "google"}
            PROVIDER_DISPLAY: dict[str, str] = {
                "deepseek": "DeepSeek", "openai": "OpenAI",
                "anthropic": "Anthropic", "google": "Google",
            }

            def _serialize(models):
                return [{
                    "id": m.id, "name": m.name,
                    "cost_per_1k_in": m.cost_per_1k_in,
                    "cost_per_1k_out": m.cost_per_1k_out,
                    "supports_tools": m.supports_tools,
                    "supports_thinking": m.supports_thinking,
                } for m in models]

            db = getattr(http._agent, "_db", None) if http._agent else None
            db_providers: dict[str, dict] = {}
            db_models: dict[str, list[dict]] = {}
            if db:
                try:
                    for row in await db.get_model_providers():
                        db_providers[row["provider"]] = row
                    for row in await db.get_model_catalog():
                        db_models.setdefault(row["provider"], []).append(row)
                except Exception:
                    pass

            resolver = (
                getattr(http._agent.router, "_credentials", None)
                if http._agent else None
            )

            providers = []
            for pid in sorted(CHAT_PROVIDERS):
                entry = PROVIDER_REGISTRY.get(pid)
                if not entry:
                    continue
                module_path, class_name, _lazy = entry
                try:
                    mod = importlib.import_module(module_path)
                    cls = getattr(mod, class_name)
                    static_models = _serialize(cls.get_available_models())
                except Exception:
                    logger.warning("api.models.providers_skip", provider=pid)
                    static_models = []

                db_rows = db_models.get(pid) or []
                if db_rows:
                    models = [{
                        "id": row["model_id"],
                        "name": row.get("display_name") or row["model_id"],
                        "cost_per_1k_in": 0.0,
                        "cost_per_1k_out": 0.0,
                        "supports_tools": "tools" in (row.get("capabilities") or ""),
                        "supports_thinking": "thinking" in (row.get("capabilities") or ""),
                    } for row in db_rows]
                else:
                    models = static_models

                cred = resolver.resolve(pid) if resolver is not None else None
                providers.append({
                    "id": pid,
                    "name": PROVIDER_DISPLAY.get(pid, pid),
                    "models": models,
                    "connected": bool(cred and cred.configured),
                    "key_source": cred.source if cred else "",
                })

            # DB 里已连接但不在静态 CHAT_PROVIDERS 的供应商
            for pid, row in db_providers.items():
                if any(item["id"] == pid for item in providers):
                    continue
                db_rows = db_models.get(pid) or []
                providers.append({
                    "id": pid,
                    "name": pid,
                    "models": [{
                        "id": item["model_id"],
                        "name": item.get("display_name") or item["model_id"],
                        "cost_per_1k_in": 0.0,
                        "cost_per_1k_out": 0.0,
                        "supports_tools": "tools" in (item.get("capabilities") or ""),
                        "supports_thinking": "thinking" in (item.get("capabilities") or ""),
                    } for item in db_rows],
                    "connected": True,
                    "key_source": row.get("key_source", "db"),
                })

            return {"providers": providers}

        # ── 添加供应商（M2-5）──
        @self.app.post("/api/models/providers")
        async def add_model_provider(request: Request):
            agent_ref = self._agent
            if not agent_ref or not agent_ref._db:
                return {"error": "agent not ready"}

            from packages.shared.provider_service import save_provider

            body = await request.json()
            provider = str(body.get("provider") or "").strip()
            api_key = str(body.get("api_key") or "").strip()
            base_url = str(body.get("base_url") or "").strip()

            try:
                models = await save_provider(
                    agent_ref._db, provider, api_key, base_url
                )
            except Exception as exc:
                logger.warning(
                    "api.models.provider_save_failed",
                    provider=provider, error=str(exc)[:200],
                )
                return {"status": "error", "error": str(exc)[:300]}

            try:
                os.environ[f"{provider.upper()}_API_KEY"] = api_key
                if base_url:
                    os.environ[f"{provider.upper()}_BASE_URL"] = base_url
                await agent_ref.router.reload_config()
            except Exception as exc:
                logger.warning(
                    "api.models.provider_reload_failed",
                    provider=provider, error=str(exc)[:200],
                )
                return {"status": "error", "error": str(exc)[:300]}

            return {
                "status": "ok",
                "provider": provider,
                "models": models,
                "key_source": "db",
            }

        # ── 删除供应商（M2-5）──
        @self.app.delete("/api/models/providers/{provider}")
        async def delete_model_provider(provider: str):
            agent_ref = self._agent
            if not agent_ref or not agent_ref._db:
                return {"error": "agent not ready"}

            router = agent_ref.router
            router_cfg = getattr(router, "routing_config", None)
            if router_cfg is not None:
                used = []
                for name, profile in router_cfg.profiles.items():
                    for model in (profile.model, *profile.fallbacks):
                        spec = router_cfg.models.get(model)
                        if spec is not None and spec.provider == provider:
                            used.append(f"{name}:{model}")
                if used:
                    return {
                        "status": "error",
                        "error": f"仍有 profile 引用该供应商模型: {', '.join(used)}",
                    }

            try:
                await agent_ref._db.delete_model_provider(provider)
                os.environ.pop(f"{provider.upper()}_API_KEY", None)
                await agent_ref.router.reload_config()
            except Exception as exc:
                return {"status": "error", "error": str(exc)[:300]}
            return {"status": "ok", "provider": provider}

        # ── 当前模型配置 ──
        @self.app.get("/api/models/config")
        async def get_model_config():
            if not http._agent or not http._agent._db:
                return {"error": "http._agent not ready"}

            try:
                db_configs = await http._agent._db.get_model_configs()
                tiers = {}
                overrides = {}
                for c in db_configs:
                    key = c["config_key"]
                    entry = {
                        "provider": c["provider"],
                        "model": c["model_name"],
                        "temperature": c.get("temperature", 0.7),
                        "max_tokens": c.get("max_tokens", 800),
                        "source": c.get("source", "legacy"),
                    }
                    if key.startswith("tier:"):
                        tiers[key.split(":", 1)[1]] = entry
                    elif key.startswith("override:"):
                        overrides[key.split(":", 1)[1]] = entry

                # 若无 DB 配置，返回内存中的默认配置
                if not tiers:
                    for tier, cfg in http._agent.router._tier_configs.items():
                        tiers[tier] = {
                            "provider": cfg.provider,
                            "model": cfg.model_name,
                            "temperature": cfg.temperature,
                            "max_tokens": cfg.max_tokens,
                        }

                embed_cfg = await http._agent._db.get_embed_config()
                embed_info = None
                if embed_cfg:
                    embed_info = {
                        "provider": embed_cfg["provider"],
                        "model": embed_cfg["model_name"],
                        "base_url": embed_cfg.get("base_url", ""),
                    }
                elif http._agent.router._embed_config:
                    rc = http._agent.router._embed_config
                    embed_info = {
                        "provider": rc.get("provider", ""),
                        "model": rc.get("model_name", ""),
                        "base_url": rc.get("base_url", ""),
                    }

                routing_v2 = bool(getattr(http._agent.router, "routing_v2", False))
                routing_info = None
                routing_config = getattr(http._agent.router, "routing_config", None)
                if routing_v2 and routing_config is not None:
                    routing_info = {
                        "version": routing_config.version,
                        "source_path": (
                            str(routing_config.source_path)
                            if routing_config.source_path else ""
                        ),
                        "providers": {
                            name: item.to_dict()
                            for name, item in routing_config.providers.items()
                        },
                        "models": {
                            name: item.to_dict()
                            for name, item in routing_config.models.items()
                        },
                        "profiles": {
                            name: item.to_dict()
                            for name, item in routing_config.profiles.items()
                        },
                        "embedding": (
                            routing_config.embedding.to_dict()
                            if routing_config.embedding else None
                        ),
                        "effective": routing_config.effective_routes(),
                    }

                return {
                    "tiers": tiers,
                    "overrides": overrides,
                    "embed": embed_info,
                    "adapters": list(http._agent.router._adapters.keys()),
                    "routing_v2": routing_v2,
                    "routing": routing_info,
                }
            except Exception as e:
                logger.warning("api.models.config_error", error=str(e))
                return {"error": str(e)}

        # ── 更新模型配置 ──
        @self.app.put("/api/models/config")
        async def update_model_config(request: Request):
            agent_ref = self._agent
            if not agent_ref or not agent_ref._db:
                return {"error": "agent not ready"}

            body = await request.json()
            tier_updates = body.get("tiers", {})
            profile_updates = body.get("profiles", {})
            api_keys: dict[str, str] = body.get("api_keys", {})
            base_urls: dict[str, str] = body.get("base_urls", {})

            import time
            now = time.time()
            errors = []

            for tier, info in tier_updates.items():
                provider = info.get("provider", "deepseek")
                model = info.get("model", "")
                if not model:
                    continue

                # Embed tier → write to embed_config table instead
                if tier == "embed":
                    try:
                        await agent_ref._db.insert_embed_config(
                            provider=provider,
                            model_name=model,
                            api_key=api_keys.get(provider, ""),
                            base_url=base_urls.get(provider, ""),
                            created_at=now, updated_at=now,
                        )
                    except Exception as e:
                        errors.append(f"embed:{tier}: {e}")
                    continue

                # Detect override: vs tier: prefix
                config_key = tier if tier.startswith("override:") else f"tier:{tier}"
                try:
                    await agent_ref._db.insert_model_config(
                        config_key=config_key,
                        provider=provider,
                        model_name=model,
                        api_key=api_keys.get(provider, ""),
                        temperature=info.get("temperature", 0.7),
                        max_tokens=info.get("max_tokens", 800),
                        source="ui",
                        created_at=now, updated_at=now,
                    )
                except Exception as e:
                    errors.append(f"tier:{tier}: {e}")

            # ── M2-3b: profile 覆盖（写入 source='ui'）──
            router = agent_ref.router
            if profile_updates:
                if not getattr(router, "routing_v2", False):
                    errors.append("profiles: MODEL_ROUTING_V2 未开启")
                else:
                    routing_config = getattr(router, "routing_config", None)
                    for name, info in profile_updates.items():
                        profile = (
                            routing_config.profiles.get(name)
                            if routing_config is not None else None
                        )
                        if profile is None:
                            errors.append(f"profile:{name}: 未知 profile")
                            continue
                        model = info.get("model") or profile.model
                        model_spec = (
                            routing_config.models.get(model)
                            if routing_config is not None else None
                        )
                        if model_spec is None:
                            errors.append(f"profile:{name}: 未知模型 {model}")
                            continue
                        fallbacks = info.get("fallbacks", list(profile.fallbacks))
                        if not isinstance(fallbacks, list) or any(
                            not isinstance(item, str) for item in fallbacks
                        ):
                            errors.append(f"profile:{name}: fallbacks 必须是字符串数组")
                            continue
                        if any(fb not in routing_config.models for fb in fallbacks):
                            errors.append(f"profile:{name}: fallbacks 含未知模型")
                            continue
                        candidates = (model, *fallbacks)
                        if not any(
                            all(
                                cap in routing_config.models[item].capabilities
                                for cap in profile.requires
                            )
                            for item in candidates
                        ):
                            errors.append(
                                f"profile:{name}: 没有满足 {list(profile.requires)} 的候选模型"
                            )
                            continue
                        try:
                            temperature = float(info.get("temperature", profile.temperature))
                            max_tokens = int(info.get("max_tokens", profile.max_tokens))
                        except (TypeError, ValueError):
                            errors.append(f"profile:{name}: temperature/max_tokens 非法")
                            continue
                        if not 0.0 <= temperature <= 2.0 or max_tokens <= 0:
                            errors.append(f"profile:{name}: temperature/max_tokens 越界")
                            continue
                        try:
                            await agent_ref._db.insert_model_config(
                                config_key=f"profile:{name}",
                                provider=info.get("provider") or model_spec.provider,
                                model_name=model,
                                api_key="",
                                temperature=temperature,
                                max_tokens=max_tokens,
                                source="ui",
                                fallbacks=json.dumps(fallbacks, ensure_ascii=False),
                                created_at=now, updated_at=now,
                            )
                        except Exception as e:
                            errors.append(f"profile:{name}: {e}")

            # ── 统一更新 os.environ（仅当 DB 写入全部成功后，reload 前一次性写入）──
            for provider, key in api_keys.items():
                if key:
                    os.environ[f"{provider.upper()}_API_KEY"] = key
            for provider, url in base_urls.items():
                if url:
                    os.environ[f"{provider.upper()}_BASE_URL"] = url

            # 热重载（仅当 os.environ 已更新）
            try:
                await agent_ref.router.reload_config()
            except Exception as e:
                errors.append(f"reload: {e}")

            if errors:
                return {"status": "partial", "errors": errors}
            return {"status": "ok"}

        # ── 恢复文件默认：删除 profile source='ui' 覆盖 ──
        @self.app.post("/api/models/config/reset")
        async def reset_model_config(request: Request):
            agent_ref = self._agent
            if not agent_ref or not agent_ref._db:
                return {"error": "agent not ready"}
            router = agent_ref.router
            if not getattr(router, "routing_v2", False):
                return {"error": "MODEL_ROUTING_V2 未开启"}

            try:
                body = await request.json()
            except Exception:
                body = {}
            profiles = body.get("profiles")
            routing_config = getattr(router, "routing_config", None)
            available = (
                list(routing_config.profiles)
                if routing_config is not None else []
            )
            targets = available if profiles is None else [
                name for name in profiles if name in available
            ]

            for name in targets:
                try:
                    await agent_ref._db.delete_model_config(f"profile:{name}")
                except Exception as exc:
                    logger.warning(
                        "api.models.reset_profile_failed",
                        profile=name, error=str(exc)[:160],
                    )
            try:
                await router.reload_config()
            except Exception as exc:
                return {"status": "partial", "errors": [f"reload: {exc}"]}
            return {"status": "ok", "reset": targets}

        # ── 自定义模型目录（M2-6）──
        @self.app.post("/api/models/catalog")
        async def add_model_catalog(request: Request):
            agent_ref = self._agent
            if not agent_ref or not agent_ref._db:
                return {"error": "agent not ready"}
            router = agent_ref.router
            routing_config = getattr(router, "routing_config", None)
            if not getattr(router, "routing_v2", False) or routing_config is None:
                return {"error": "MODEL_ROUTING_V2 未开启"}

            body = await request.json()
            provider = str(body.get("provider") or "").strip()
            model_id = str(body.get("model_id") or "").strip()
            display_name = str(body.get("display_name") or model_id).strip()
            capabilities = body.get("capabilities") or []
            if provider not in routing_config.providers:
                return {"status": "error", "error": f"未知供应商 {provider}"}
            if not model_id:
                return {"status": "error", "error": "模型 ID 不能为空"}
            if not isinstance(capabilities, list) or any(
                not isinstance(cap, str) for cap in capabilities
            ):
                return {"status": "error", "error": "capabilities 必须是字符串数组"}
            allowed = {"tools", "vision", "streaming", "thinking"}
            if set(capabilities) - allowed:
                return {"status": "error", "error": "capabilities 含未知能力"}
            try:
                context_window = int(body.get("context_window", 128000))
                max_output_tokens = int(body.get("max_output_tokens", 8000))
            except (TypeError, ValueError):
                return {"status": "error", "error": "context/max_output 非法"}
            if context_window <= 0 or max_output_tokens <= 0:
                return {"status": "error", "error": "context/max_output 必须大于 0"}

            try:
                await agent_ref._db.upsert_model_catalog(
                    provider=provider,
                    model_id=model_id,
                    display_name=display_name,
                    capabilities=capabilities,
                    context_window=context_window,
                    max_output_tokens=max_output_tokens,
                    source="manual",
                )
                await router.reload_config()
            except Exception as exc:
                return {"status": "error", "error": str(exc)[:300]}
            return {
                "status": "ok",
                "provider": provider,
                "model_id": model_id,
                "display_name": display_name,
                "capabilities": capabilities,
            }

        @self.app.delete("/api/models/catalog")
        async def delete_model_catalog(request: Request):
            agent_ref = self._agent
            if not agent_ref or not agent_ref._db:
                return {"error": "agent not ready"}
            router = agent_ref.router
            routing_config = getattr(router, "routing_config", None)
            if not getattr(router, "routing_v2", False) or routing_config is None:
                return {"error": "MODEL_ROUTING_V2 未开启"}

            body = await request.json()
            provider = str(body.get("provider") or "").strip()
            model_id = str(body.get("model_id") or "").strip()
            if not provider or not model_id:
                return {"status": "error", "error": "provider/model_id 不能为空"}

            for name, profile in routing_config.profiles.items():
                if model_id in (profile.model, *profile.fallbacks):
                    return {
                        "status": "error",
                        "error": f"profile {name} 仍在使用 {model_id}",
                    }

            rows = await agent_ref._db.get_model_catalog(provider)
            if not any(row.get("model_id") == model_id for row in rows):
                return {"status": "error", "error": "只能删除通过 UI 添加的模型"}
            try:
                await agent_ref._db.delete_model_catalog(provider, model_id)
                await router.reload_config()
            except Exception as exc:
                return {"status": "error", "error": str(exc)[:300]}
            return {"status": "ok", "provider": provider, "model_id": model_id}

        # ── 验证 API Key ──
        @self.app.post("/api/models/validate")
        async def validate_api_key(request: Request):
            body = await request.json()
            provider = body.get("provider", "")
            api_key = body.get("api_key", "")

            if not provider or not api_key:
                return {"valid": False, "error": "provider and api_key required"}

            try:
                from openai import AsyncOpenAI

                base_urls = {
                    "deepseek": "https://api.deepseek.com",
                    "openai": "https://api.openai.com/v1",
                    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
                }

                # Anthropic 不是 OpenAI 兼容端点，使用专用 SDK 验证
                if provider == "anthropic":
                    try:
                        from anthropic import AsyncAnthropic
                        ac = AsyncAnthropic(
                            api_key=api_key,
                            base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                        )
                        # 发送极短请求验证 Key（Anthropic 不提供 list models 端点）
                        await asyncio.wait_for(
                            ac.messages.create(
                                model="claude-haiku-4-6",
                                max_tokens=1,
                                messages=[{"role": "user", "content": "hi"}],
                            ),
                            timeout=15,
                        )
                        return {"valid": True}
                    except ImportError:
                        return {"valid": True, "verified": False, "note": "Anthropic SDK 未安装，跳过验证"}
                    except Exception as e:
                        return {"valid": False, "error": str(e)[:200]}

                base_url = base_urls.get(provider)
                if not base_url:
                    return {"valid": True, "verified": False, "note": "无法验证此供应商，请直接使用"}
                client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                await asyncio.wait_for(
                    client.models.list(),
                    timeout=10,
                )
                return {"valid": True}
            except Exception as e:
                return {"valid": False, "error": str(e)[:200]}

    async def send(self, text: str) -> None:
        """HTTP 通道不通过 send() 输出"""
        pass

    async def stop(self) -> None:
        """关闭 HTTP 服务器"""
        if self._server:
            self._server.should_exit = True
            logger.info("http.stopped")
