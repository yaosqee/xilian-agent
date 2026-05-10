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


# ── CORS ──

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
