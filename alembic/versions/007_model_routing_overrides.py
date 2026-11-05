"""model_configs: source + fallbacks for M2 routing overrides

Revision ID: 007_model_routing_overrides
Revises: 006_conversation_logs_images
Create Date: 2026-11-05
"""
from alembic import op


revision = "007_model_routing_overrides"
down_revision = "006_conversation_logs_images"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite 支持 ADD COLUMN；已有行统一视为 legacy，V2 只消费 source='ui'。
    op.execute(
        "ALTER TABLE model_configs ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy'"
    )
    op.execute(
        "ALTER TABLE model_configs ADD COLUMN fallbacks TEXT DEFAULT ''"
    )


def downgrade():
    # SQLite 不支持 DROP COLUMN（旧版本），保留列。
    pass
