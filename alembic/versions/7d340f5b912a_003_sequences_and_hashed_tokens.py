"""Transactional TV numbers and hashed device credentials.

Revision ID: 7d340f5b912a
Revises: 9c7e2b4a610f
"""
import hashlib
from alembic import op
import sqlalchemy as sa

revision = "7d340f5b912a"
down_revision = "9c7e2b4a610f"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "number_sequences" not in tables:
        op.create_table("number_sequences",
            sa.Column("name", sa.String(80), primary_key=True),
            sa.Column("value", sa.BigInteger(), nullable=False))

    for table, column, floor in (
        ("screens", "screen_number", 1000), ("campaigns", "campaign_number", 2000),
        ("playlists", "playlist_number", 3000), ("media_assets", "media_number", 5000),
    ):
        maximum = bind.execute(sa.text(f"SELECT MAX({column}) FROM {table}")).scalar()
        value = max(maximum or 0, floor)
        missing = bind.execute(sa.text(f"SELECT id FROM {table} WHERE {column} IS NULL ORDER BY id")).scalars().all()
        for row_id in missing:
            value += 1
            bind.execute(sa.text(f"UPDATE {table} SET {column}=:value WHERE id=:id"), {"value": value, "id": row_id})
        existing = bind.execute(sa.text("SELECT value FROM number_sequences WHERE name = :name"), {"name": table}).scalar()
        if existing is None:
            bind.execute(sa.text("INSERT INTO number_sequences (name, value) VALUES (:name, :value)"),
                         {"name": table, "value": value})
        else:
            bind.execute(sa.text("UPDATE number_sequences SET value = :value WHERE name = :name"),
                         {"name": table, "value": max(existing, value)})

    credentials = bind.execute(sa.text("SELECT screen_id, token_hash FROM device_credentials")).all()
    for screen_id, token in credentials:
        if token and not token.startswith("sha256:"):
            digest = "sha256:" + hashlib.sha256(token.encode()).hexdigest()
            bind.execute(sa.text("UPDATE device_credentials SET token_hash=:token WHERE screen_id=:id"),
                         {"token": digest, "id": screen_id})


def downgrade():
    # Hashes cannot be reversed; older servers must rotate credentials after rollback.
    op.drop_table("number_sequences")
