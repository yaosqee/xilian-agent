"""V3.7: add images column to conversation_logs

Reason: conversation_logs was missing the images column that insert_log()
has been inserting since multimodal support was added.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_conversation_logs_images'
down_revision = '005_notebook_due_date'
branch_labels = None
depends_on = None


def upgrade():
    try:
        op.add_column('conversation_logs',
            sa.Column('images', sa.Text, server_default='[]'))
    except Exception:
        pass  # Column may already exist (manual init path added it)


def downgrade():
    # SQLite doesn't support DROP COLUMN in older versions; skip
    pass
