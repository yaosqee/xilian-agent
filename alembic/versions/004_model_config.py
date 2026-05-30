"""add model_configs + embed_config tables

Revision ID: 004_model_config
Revises: 003_affection
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa
import os
import time

revision = '004_model_config'
down_revision = '003_affection'
branch_labels = None
depends_on = None


def upgrade():
    # model_configs
    op.create_table(
        'model_configs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('config_key', sa.String, nullable=False, unique=True),
        sa.Column('provider', sa.String, nullable=False),
        sa.Column('model_name', sa.String, nullable=False),
        sa.Column('api_key', sa.String, nullable=False, server_default=''),
        sa.Column('base_url', sa.String, server_default=''),
        sa.Column('temperature', sa.Float, server_default='0.7'),
        sa.Column('max_tokens', sa.Integer, server_default='800'),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('updated_at', sa.Float, nullable=False),
    )
    op.create_index('idx_model_config_key', 'model_configs', ['config_key'])
    op.create_index('idx_model_config_provider', 'model_configs', ['provider', 'is_active'])

    # embed_config
    op.create_table(
        'embed_config',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('provider', sa.String, nullable=False),
        sa.Column('model_name', sa.String, nullable=False),
        sa.Column('api_key', sa.String, nullable=False, server_default=''),
        sa.Column('base_url', sa.String, server_default=''),
        sa.Column('dimensions', sa.Integer, server_default='1024'),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('updated_at', sa.Float, nullable=False),
    )
    op.create_index('idx_embed_config_provider', 'embed_config', ['provider', 'is_active'])

    # Auto-seed from .env if DeepSeek key is configured (backward compat)
    _auto_seed_from_env()


def downgrade():
    op.drop_table('embed_config')
    op.drop_table('model_configs')


def _auto_seed_from_env():
    """Migration-phase auto-seed: if DEEPSEEK_API_KEY exists, create default configs."""
    ds_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not ds_key:
        return

    now = time.time()
    conn = op.get_bind()

    # Default tier configs (DeepSeek-only)
    tiers = [
        ("tier:powerful", "deepseek", "deepseek-v4-pro", ds_key, 0.65, 800),
        ("tier:fast", "deepseek", "deepseek-v4-flash", ds_key, 0.3, 800),
        ("tier:reasoning", "deepseek", "deepseek-reasoner", ds_key, 0.3, 2000),
    ]
    for key, provider, model, api_key, temp, max_tok in tiers:
        conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO model_configs "
                "(config_key, provider, model_name, api_key, temperature, max_tokens, "
                " is_active, created_at, updated_at) "
                "VALUES (:key, :provider, :model, :api_key, :temp, :max_tok, 1, :now, :now)"
            ),
            {"key": key, "provider": provider, "model": model, "api_key": api_key,
             "temp": temp, "max_tok": max_tok, "now": now},
        )

    # Default embed config
    embed_key = os.getenv("EMBED_API_KEY") or os.getenv("DEEPSEEK_API_KEY_2") or ds_key
    embed_base = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
    embed_model = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
    conn.execute(
        sa.text(
            "INSERT OR IGNORE INTO embed_config "
            "(id, provider, model_name, api_key, base_url, dimensions, "
            " is_active, created_at, updated_at) "
            "VALUES (1, 'siliconflow', :model, :api_key, :base_url, 1024, 1, :now, :now)"
        ),
        {"model": embed_model, "api_key": embed_key, "base_url": embed_base, "now": now},
    )
