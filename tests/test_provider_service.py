"""M2-5c: onboarding/provider service 保存路径。"""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, ".")

from packages.shared.provider_service import save_provider


@pytest.mark.asyncio
async def test_save_provider_validates_then_writes_catalog():
    db = SimpleNamespace(
        upsert_model_provider=AsyncMock(),
        replace_model_catalog=AsyncMock(),
    )
    models = [{"model_id": "m1", "capabilities": ["tools"]}]

    with patch(
        "packages.shared.provider_service.validate_provider_key",
        AsyncMock(),
    ) as validate, patch(
        "packages.shared.provider_service.static_model_catalog",
        return_value=models,
    ):
        result = await save_provider(db, "deepseek", "sk-test")

    validate.assert_awaited_once_with("deepseek", "sk-test", None)
    db.upsert_model_provider.assert_awaited_once()
    assert db.replace_model_catalog.await_args.args == ("deepseek", models)
    assert result == models


@pytest.mark.asyncio
async def test_save_provider_rejects_unknown_provider():
    db = SimpleNamespace(
        upsert_model_provider=AsyncMock(),
        replace_model_catalog=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match="暂不支持"):
        await save_provider(db, "unknown", "sk-test")
    db.upsert_model_provider.assert_not_called()
