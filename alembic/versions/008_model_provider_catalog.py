"""model_providers + model_catalog for UI-managed providers (M2-5)

Revision ID: 008_model_provider_catalog
Revises: 007_model_routing_overrides
Create Date: 2026-11-05
"""
from alembic import op


revision = "008_model_provider_catalog"
down_revision = "007_model_routing_overrides"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_providers (
            provider    TEXT PRIMARY KEY,
            base_url    TEXT DEFAULT '',
            api_key     TEXT DEFAULT '',
            key_source  TEXT DEFAULT 'db',
            enabled     INTEGER DEFAULT 1,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_catalog (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            provider            TEXT NOT NULL,
            model_id            TEXT NOT NULL,
            display_name        TEXT DEFAULT '',
            capabilities        TEXT DEFAULT '[]',
            context_window      INTEGER DEFAULT 128000,
            max_output_tokens   INTEGER DEFAULT 8000,
            source              TEXT DEFAULT 'builtin',
            enabled             INTEGER DEFAULT 1,
            created_at          REAL NOT NULL,
            updated_at          REAL NOT NULL,
            UNIQUE(provider, model_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_catalog_provider "
        "ON model_catalog(provider, enabled)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS model_catalog")
    op.execute("DROP TABLE IF EXISTS model_providers")
