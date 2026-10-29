"""Add identifiers used by the native TV protocol.

Revision ID: 9c7e2b4a610f
Revises: 585b4edb4711
"""
from alembic import op
import sqlalchemy as sa

revision = "9c7e2b4a610f"
down_revision = "585b4edb4711"
branch_labels = None
depends_on = None

COLUMNS = (
    ("screens", "screen_number", sa.Integer()),
    ("screens", "pairing_code", sa.String(16)),
    ("campaigns", "campaign_number", sa.Integer()),
    ("playlists", "playlist_number", sa.Integer()),
    ("media_assets", "media_number", sa.Integer()),
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, column, column_type in COLUMNS:
        cols = [c["name"] for c in inspector.get_columns(table)]
        if column not in cols:
            op.add_column(table, sa.Column(column, column_type, nullable=True))
        indices = [idx["name"] for idx in inspector.get_indexes(table)]
        if f"ix_{table}_{column}" not in indices:
            op.create_index(f"ix_{table}_{column}", table, [column], unique=True)


def downgrade():
    for table, column, _ in reversed(COLUMNS):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_column(table, column)
