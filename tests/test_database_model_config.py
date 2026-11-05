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
