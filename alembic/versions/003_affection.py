"""add affection_state table

Revision ID: 003_affection
Revises: 002_audit_logs
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = '003_affection'
down_revision = '002_audit_logs'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'affection_state',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('score', sa.Float, nullable=False, server_default='0.0'),
        sa.Column('level', sa.Integer, nullable=False, server_default='1'),
        sa.Column('total_conversations', sa.Integer, nullable=False, server_default='0'),
        sa.Column('reason', sa.Text),
        sa.Column('updated_at', sa.Float, nullable=False),
    )
    op.create_index('idx_affection_updated', 'affection_state', ['updated_at'])


def downgrade():
    op.drop_table('affection_state')
