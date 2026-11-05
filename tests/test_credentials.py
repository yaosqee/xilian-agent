"""M2-5: CredentialResolver DB > env。"""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, ".")

from packages.shared.credentials import CredentialResolver


@pytest.mark.asyncio
async def test_db_key_wins_over_env():
    db = SimpleNamespace(get_model_providers=AsyncMock(return_value=[{
        "provider": "deepseek",
        "api_key": "db-key",
        "base_url": "https://db.example",
        "key_source": "db",
    }]))
    resolver = CredentialResolver(db, env={"DEEPSEEK_API_KEY": "env-key"})
    await resolver.load()

    cred = resolver.resolve("deepseek")

    assert cred.api_key == "db-key"
    assert cred.base_url == "https://db.example"
    assert cred.source == "db"


@pytest.mark.asyncio
async def test_env_fallback_when_no_db_provider():
    db = SimpleNamespace(get_model_providers=AsyncMock(return_value=[]))
    resolver = CredentialResolver(db, env={"OPENAI_API_KEY": "env-key"})
    await resolver.load()

    cred = resolver.resolve("openai")

    assert cred.api_key == "env-key"
    assert cred.source == "env"


@pytest.mark.asyncio
async def test_missing_key_is_unconfigured():
    db = SimpleNamespace(get_model_providers=AsyncMock(return_value=[]))
    resolver = CredentialResolver(db, env={})
    await resolver.load()

    cred = resolver.resolve("google")

    assert cred.configured is False
    assert cred.source == ""
