"""add audit_logs table — stage 8

Revision ID: 002_audit_logs
Revises: 001_initial
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = '002_audit_logs'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.Float, nullable=False),
        sa.Column('event_type', sa.Text, nullable=False),
        sa.Column('severity', sa.Text, server_default='info'),
        sa.Column('source', sa.Text, server_default='system'),
        sa.Column('detail', sa.Text),
        sa.Column('user_id', sa.Text, server_default='hezi'),
        sa.Column('trace_id', sa.Text),
    )
    op.create_index('idx_audit_timestamp', 'audit_logs', ['timestamp'])
    op.create_index('idx_audit_type', 'audit_logs', ['event_type', 'timestamp'])


def downgrade():
    op.drop_table('audit_logs')
