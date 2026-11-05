"""M2-3b: model_configs source/fallbacks round-trip。"""
import sys

import pytest

sys.path.insert(0, ".")

from packages.shared.database import DatabaseManager


@pytest.mark.asyncio
async def test_model_config_source_and_fallbacks_roundtrip(tmp_path):
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    try:
        await db.insert_model_config(
            config_key="profile:dialogue",
            provider="deepseek",
            model_name="deepseek-v4-pro",
            temperature=0.5,
            max_tokens=900,
            source="ui",
            fallbacks='["deepseek-flash"]',
        )
        rows = await db.get_model_configs()
        row = next(r for r in rows if r["config_key"] == "profile:dialogue")
        assert row["source"] == "ui"
        assert row["fallbacks"] == '["deepseek-flash"]'
        assert row["model_name"] == "deepseek-v4-pro"

        await db.delete_model_config("profile:dialogue")
        rows = await db.get_model_configs()
        assert all(r["config_key"] != "profile:dialogue" for r in rows)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_model_provider_and_catalog_roundtrip(tmp_path):
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    try:
        await db.upsert_model_provider(
            "openai", api_key="sk-test", base_url="https://api.openai.com/v1",
        )
        providers = await db.get_model_providers()
        assert providers[0]["provider"] == "openai"
        assert providers[0]["api_key"] == "sk-test"

        await db.replace_model_catalog("openai", [{
            "model_id": "gpt-test",
            "display_name": "GPT Test",
            "capabilities": ["tools"],
            "context_window": 64000,
            "max_output_tokens": 4000,
        }])
        catalog = await db.get_model_catalog("openai")
        assert catalog[0]["model_id"] == "gpt-test"
        assert '"tools"' in catalog[0]["capabilities"]

        await db.delete_model_provider("openai")
        assert await db.get_model_providers() == []
        assert await db.get_model_catalog("openai") == []
    finally:
        await db.close()

