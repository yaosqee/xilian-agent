"""initial schema — stages 0-7

Revision ID: 001_initial
Revises: None
Create Date: 2026-05-16

All tables from stages 0 through 7b:
  conversation_logs, episodic_memories, message_queue,
  emotion_snapshots, autobiography_entries, reflection_crystals,
  autonomy_settings, notebook_entries, scheduled_tasks
"""
from alembic import op
import sqlalchemy as sa

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ── conversation_logs ──
    op.create_table(
        'conversation_logs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.Float, nullable=False),
        sa.Column('session_id', sa.Text, nullable=False),
        sa.Column('event_id', sa.Text, nullable=False, unique=True),
        sa.Column('user_message', sa.Text, nullable=False),
        sa.Column('assistant_reply', sa.Text, nullable=False),
        sa.Column('emotion_label', sa.Text),
        sa.Column('emotion_primary', sa.Text),
        sa.Column('emotion_intensity', sa.Float),
        sa.Column('user_id', sa.Text, server_default='hezi'),
        sa.Column('source', sa.Text, server_default='console'),
    )
    op.create_index('idx_logs_timestamp', 'conversation_logs', ['timestamp'])
    op.create_index('idx_logs_session', 'conversation_logs', ['session_id'])
    op.create_index('idx_logs_emotion', 'conversation_logs', ['emotion_primary'])

    # ── episodic_memories ──
    op.create_table(
        'episodic_memories',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.Float, nullable=False),
        sa.Column('summary', sa.Text, nullable=False),
        sa.Column('raw_conversation', sa.Text, nullable=False),
        sa.Column('emotion_tags', sa.Text),
        sa.Column('importance', sa.Float, server_default='0.5'),
        sa.Column('embedding_id', sa.Text),
        sa.Column('embedding_model', sa.Text, server_default='bge-m3'),
        sa.Column('embedding_version', sa.Text, server_default='v1'),
        sa.Column('embedding_status', sa.Text, server_default='pending'),
        sa.Column('access_count', sa.Integer, server_default='0'),
        sa.Column('last_accessed', sa.Float),
        sa.Column('session_id', sa.Text, nullable=False),
    )
    op.create_index('idx_episodic_timestamp', 'episodic_memories', ['timestamp'])
    op.create_index('idx_episodic_importance', 'episodic_memories', ['importance'])
    op.create_index('idx_episodic_status', 'episodic_memories', ['embedding_status'])
    op.create_index('idx_episodic_embedding', 'episodic_memories', ['embedding_id'])

    # ── message_queue ──
    op.create_table(
        'message_queue',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('event_id', sa.Text, nullable=False, unique=True),
        sa.Column('payload', sa.Text, nullable=False),
        sa.Column('status', sa.Text, server_default='pending'),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('started_at', sa.Float),
        sa.Column('completed_at', sa.Float),
        sa.Column('error_msg', sa.Text),
        sa.Column('retry_count', sa.Integer, server_default='0'),
    )
    op.create_index('idx_queue_status', 'message_queue', ['status', 'created_at'])
    op.create_index('idx_queue_event', 'message_queue', ['event_id'])

    # ── emotion_snapshots ──
    op.create_table(
        'emotion_snapshots',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.Float, nullable=False),
        sa.Column('pad_p', sa.Float, nullable=False, server_default='0.0'),
        sa.Column('pad_a', sa.Float, nullable=False, server_default='0.0'),
        sa.Column('pad_d', sa.Float, nullable=False, server_default='0.0'),
        sa.Column('primary_emotion', sa.Text),
        sa.Column('primary_intensity', sa.Float),
        sa.Column('dimensions_json', sa.Text),
        sa.Column('appraisal_relevance', sa.Float),
        sa.Column('appraisal_facilitation', sa.Float),
        sa.Column('appraisal_coping', sa.Float),
        sa.Column('source', sa.Text, server_default='appraisal'),
        sa.Column('session_id', sa.Text, nullable=False),
        sa.Column('trace_id', sa.Text),
    )
    op.create_index('idx_emo_timestamp', 'emotion_snapshots', ['timestamp'])
    op.create_index('idx_emo_session', 'emotion_snapshots', ['session_id'])

    # ── autobiography_entries ──
    op.create_table(
        'autobiography_entries',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('date', sa.Text, nullable=False, unique=True),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('word_count', sa.Integer, server_default='0'),
        sa.Column('mood_summary', sa.Text),
        sa.Column('key_memories', sa.Text),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('session_id', sa.Text, nullable=False),
    )
    op.create_index('idx_auto_date', 'autobiography_entries', ['date'])

    # ── reflection_crystals ──
    op.create_table(
        'reflection_crystals',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('week_start', sa.Text, nullable=False),
        sa.Column('week_end', sa.Text, nullable=False),
        sa.Column('learned', sa.Text),
        sa.Column('surprised', sa.Text),
        sa.Column('grateful', sa.Text),
        sa.Column('remember', sa.Text),
        sa.Column('raw_prompt', sa.Text),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('session_id', sa.Text, nullable=False),
    )
    op.create_index('idx_ref_week', 'reflection_crystals', ['week_start'])

    # ── autonomy_settings ──
    op.create_table(
        'autonomy_settings',
        sa.Column('key', sa.Text, primary_key=True),
        sa.Column('value', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Float, nullable=False),
    )

    # ── notebook_entries (7b) ──
    op.create_table(
        'notebook_entries',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('kind', sa.Text, nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('tags', sa.Text),
        sa.Column('importance', sa.Float, server_default='0.5'),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('session_id', sa.Text, nullable=False),
    )
    op.create_index('idx_notebook_kind', 'notebook_entries', ['kind', 'created_at'])
    op.create_index('idx_notebook_active', 'notebook_entries', ['is_active', 'created_at'])

    # ── scheduled_tasks (7b) ──
    op.create_table(
        'scheduled_tasks',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('title', sa.Text, nullable=False),
        sa.Column('details', sa.Text),
        sa.Column('priority', sa.Integer, server_default='0'),
        sa.Column('status', sa.Text, server_default='pending'),
        sa.Column('due_at', sa.Float),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('completed_at', sa.Float),
        sa.Column('session_id', sa.Text, nullable=False),
    )
    op.create_index('idx_tasks_status', 'scheduled_tasks', ['status', 'due_at'])
    op.create_index('idx_tasks_due', 'scheduled_tasks', ['due_at'],
                    postgresql_where=sa.text("status='pending'"))


def downgrade():
    op.drop_table('scheduled_tasks')
    op.drop_table('notebook_entries')
    op.drop_table('autonomy_settings')
    op.drop_table('reflection_crystals')
    op.drop_table('autobiography_entries')
    op.drop_table('emotion_snapshots')
    op.drop_table('message_queue')
    op.drop_table('episodic_memories')
    op.drop_table('conversation_logs')
