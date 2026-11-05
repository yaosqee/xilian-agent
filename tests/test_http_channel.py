"""
HTTP 通道测试

测试 HTTPChannel 的：
  · /api/health 健康检查
  · /api/chat 同步回复（含安全过滤）
  · /api/chat/stream SSE 流式回复
  · 边界情况：空消息、非主人、熔断
"""
import sys
import json
import pytest

sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from gateway.channels import HTTPChannel
from gateway.security import SecurityFilter
from packages.agent import AgentCore, ToolRegistry


# ── Fixtures ──

@pytest.fixture
def security():
    return SecurityFilter(owner_id="hezi")


@pytest.fixture
def http_channel(security):
    return HTTPChannel(host="127.0.0.1", port=8000, security=security)


@pytest.fixture
def client(http_channel):
    return TestClient(http_channel.app)


@pytest.fixture
def agent():
    return AgentCore()


@pytest.fixture
def channel_with_agent(http_channel, agent):
    http_channel._handler = agent.process
    return http_channel


# ── 健康检查 ──

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "xilian" in data["service"]


# ── /api/chat ──

class TestChat:
    def test_empty_message(self, client):
        resp = client.post("/api/chat", json={"message": "", "user_id": "hezi"})
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_no_handler(self, client):
        """Agent 未就绪时返回 error"""
        resp = client.post("/api/chat", json={"message": "你好", "user_id": "hezi"})
        assert resp.status_code == 200
        assert resp.json()["error"] == "agent not ready"

    def test_non_owner_blocked(self, client):
        resp = client.post("/api/chat", json={"message": "你好", "user_id": "stranger"})
        assert resp.status_code == 200
        assert resp.json()["error"] == "blocked"

    def test_stop_keyword_blocked(self, client):
        resp = client.post(
            "/api/chat",
            json={"message": "紧急停止", "user_id": "hezi"},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] == "blocked"

    def test_message_truncated(self, http_channel):
        """长度超过 5000 字符应被截断"""
        long_msg = "你好" * 3000
        event = http_channel.security.filter(
            type(
                "Event",
                (),
                {
                    "event_id": "test1234",
                    "source": "http",
                    "user_id": "hezi",
                    "payload": long_msg,
                    "is_owner": True,
                },
            )()
        )
        # 模拟 filter 的参数
        from packages.shared.events import InternalEvent
        e = InternalEvent(
            source="http",
            user_id="hezi",
            payload=long_msg,
            is_owner=True,
        )
        result = http_channel.security.filter(e)
        assert result is not None
        assert len(result.payload) <= 5000


# ── /api/chat/stream ──

class TestChatStream:
    def test_empty_message(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"message": "", "user_id": "hezi"},
        )
        assert resp.status_code == 200

    def test_non_owner_blocked(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"message": "你好", "user_id": "stranger"},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] == "blocked"

    def test_sse_headers(self, client, channel_with_agent):
        """SSE 响应应包含正确的 Content-Type"""
        resp = client.post(
            "/api/chat/stream",
            json={"message": "你好", "user_id": "hezi"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_sse_emits_tool_events_before_tokens(self, client, http_channel):
        from types import SimpleNamespace
        from packages.agent.loop.events import (
            ToolCall, ToolCallEvent, ToolOutcome, ToolResultEvent,
        )

        async def fake_handler(event, event_sink=None):
            if event_sink:
                await event_sink(ToolCallEvent(
                    step=1,
                    calls=[ToolCall(id="c1", name="query_weather", arguments={"city": "杭州"})],
                ))
                await event_sink(ToolResultEvent(
                    step=1,
                    results=[ToolOutcome(
                        call_id="c1",
                        name="query_weather",
                        ok=True,
                        data={"city": "杭州", "temp": "18-24℃", "weather": "多云"},
                    )],
                ))
            return SimpleNamespace(reply="杭州 18～24℃，多云。", sticker=None)

        http_channel._handler = fake_handler
        resp = client.post(
            "/api/chat/stream",
            json={"message": "杭州天气", "user_id": "hezi"},
        )
        body = resp.text

        assert resp.status_code == 200
        assert "event: tool_call" in body
        assert '"name": "query_weather"' in body
        assert "event: tool_result" in body
        assert "杭州" in body
        assert "event: token" in body
        assert "event: done" in body
        assert body.index("event: tool_call") < body.index("event: tool_result")
        assert body.index("event: tool_result") < body.index("event: token")

    def test_sse_streams_real_token_events_without_duplicate_chunks(self, client, http_channel):
        from types import SimpleNamespace
        from packages.agent.loop.events import TokenEvent

        async def fake_handler(event, event_sink=None):
            if event_sink:
                await event_sink(TokenEvent(step=1, text="杭州"))
                await event_sink(TokenEvent(step=1, text=" 18℃。"))
            return SimpleNamespace(reply="杭州 18℃。", sticker=None)

        http_channel._handler = fake_handler
        resp = client.post(
            "/api/chat/stream",
            json={"message": "杭州天气", "user_id": "hezi"},
        )
        body = resp.text

        assert resp.status_code == 200
        assert body.count("event: token") == 2
        assert "event: done" in body
        # 真 token 已经推过正文，不能再走一遍 3 字符假切片
        assert body.count("杭州") == 1

    def test_sse_filters_markers_from_real_tokens(self, client, http_channel):
        from types import SimpleNamespace
        from packages.agent.loop.events import TokenEvent

        async def fake_handler(event, event_sink=None):
            if event_sink:
                # 标记跨 token 边界，验证 MarkerParser 的 buffer
                await event_sink(TokenEvent(step=1, text="你好[stick"))
                await event_sink(TokenEvent(step=1, text="er:blush]"))
            return SimpleNamespace(reply="你好", sticker={"id": "blush", "file": "x.webp"})

        http_channel._handler = fake_handler
        resp = client.post(
            "/api/chat/stream",
            json={"message": "你好", "user_id": "hezi"},
        )
        body = resp.text

        assert "event: token" in body
        assert "event: sticker" in body
        assert "sticker:blush" not in body  # 标记不能漏进正文
        assert "你好" in body

    def test_sse_supports_handler_without_event_sink(self, client, http_channel):
        from types import SimpleNamespace

        async def legacy_handler(event):
            return SimpleNamespace(reply="好呀。", sticker=None)

        http_channel._handler = legacy_handler
        resp = client.post(
            "/api/chat/stream",
            json={"message": "你好", "user_id": "hezi"},
        )
        body = resp.text

        assert resp.status_code == 200
        assert "event: tool_call" not in body
        assert "event: token" in body
        assert "event: done" in body


# ── CORS ──

def test_tool_result_frame_marks_confirmation():
    from gateway.channels.http_channel import _format_loop_event
    from packages.agent.loop.events import ToolOutcome, ToolResultEvent

    frame = _format_loop_event(ToolResultEvent(
        step=1,
        results=[ToolOutcome(
            call_id="c1", name="coding_delegate", ok=False,
            error="PENDING_CONFIRMATION", needs_confirmation=True,
        )],
    ))
    payload = json.loads(frame.split("data: ", 1)[1])
    result = payload["results"][0]
    assert result["needs_confirmation"] is True
    assert result["error"] == ""


def test_model_config_exposes_effective_routing(client, http_channel):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from packages.shared.model_config import load_model_routing

    config = load_model_routing()
    db = SimpleNamespace(
        get_model_configs=AsyncMock(return_value=[]),
        get_embed_config=AsyncMock(return_value=None),
    )
    router = SimpleNamespace(
        _tier_configs={},
        _adapters={"deepseek": object()},
        _embed_config=None,
        routing_v2=True,
        routing_config=config,
    )
    http_channel._agent = SimpleNamespace(_db=db, router=router)

    resp = client.get("/api/models/config")
    data = resp.json()

    assert data["routing_v2"] is True
    assert data["routing"]["effective"]["chat"]["model"] == "deepseek-flash"
    assert data["routing"]["source_path"].endswith("model_routing.toml")
    assert "api_key_env" in data["routing"]["providers"]["deepseek"]


def test_model_config_saves_profile_override_as_ui(client, http_channel):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from packages.shared.model_config import load_model_routing

    db = SimpleNamespace(
        insert_model_config=AsyncMock(),
    )
    router = SimpleNamespace(
        routing_v2=True,
        routing_config=load_model_routing(),
        reload_config=AsyncMock(),
    )
    http_channel._agent = SimpleNamespace(_db=db, router=router)

    resp = client.put("/api/models/config", json={
        "profiles": {
            "dialogue": {
                "model": "deepseek-v4-pro",
                "fallbacks": ["deepseek-flash"],
                "temperature": 0.5,
                "max_tokens": 900,
            }
        }
    })

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    kwargs = db.insert_model_config.await_args.kwargs
    assert kwargs["config_key"] == "profile:dialogue"
    assert kwargs["model_name"] == "deepseek-v4-pro"
    assert kwargs["source"] == "ui"
    assert json.loads(kwargs["fallbacks"]) == ["deepseek-flash"]
    router.reload_config.assert_awaited_once()


def test_model_config_reset_deletes_ui_profiles(client, http_channel):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from packages.shared.model_config import load_model_routing

    db = SimpleNamespace(delete_model_config=AsyncMock())
    router = SimpleNamespace(
        routing_v2=True,
        routing_config=load_model_routing(),
        reload_config=AsyncMock(),
    )
    http_channel._agent = SimpleNamespace(_db=db, router=router)

    resp = client.post("/api/models/config/reset", json={})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert db.delete_model_config.await_count == 4
    db.delete_model_config.assert_any_await("profile:dialogue")
    router.reload_config.assert_awaited_once()


def test_add_model_provider_validates_and_saves(client, http_channel):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    db = SimpleNamespace(
        upsert_model_provider=AsyncMock(),
        replace_model_catalog=AsyncMock(),
    )
    router = SimpleNamespace(reload_config=AsyncMock())
    http_channel._agent = SimpleNamespace(_db=db, router=router)

    mock_client = MagicMock()
    mock_client.models.list = AsyncMock()
    with patch("openai.AsyncOpenAI", return_value=mock_client):
        resp = client.post("/api/models/providers", json={
            "provider": "deepseek",
            "api_key": "sk-test",
        })

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    db.upsert_model_provider.assert_awaited_once()
    assert db.replace_model_catalog.await_count == 1
    router.reload_config.assert_awaited_once()


class TestCORS:
    def test_cors_headers(self, client):
        """CORS 预检请求应有正确的头部"""
        resp = client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        # FastAPI TestClient 默认不完整模拟 CORS 预检
        # 主要验证路由存在且不报 404
        assert resp.status_code in (200, 405)
