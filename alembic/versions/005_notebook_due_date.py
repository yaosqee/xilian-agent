"""add due_date column to notebook_entries

Revision ID: 005_notebook_due_date
Revises: 004_model_config
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = '005_notebook_due_date'
down_revision = '004_model_config'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE notebook_entries ADD COLUMN due_date REAL"
    )


def downgrade():
    # SQLite 不支持 DROP COLUMN，跳过
    pass
