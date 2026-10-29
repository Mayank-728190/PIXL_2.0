"""Consume authenticator time steps once per account.

Revision ID: d10a29e31765
Revises: b4e0c019a624
"""
from alembic import op
import sqlalchemy as sa

revision = "d10a29e31765"
down_revision = "b4e0c019a624"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("last_totp_counter", sa.BigInteger(), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_totp_counter")
