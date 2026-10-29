"""Durable media processing leases and retry state.

Revision ID: b4e0c019a624
Revises: 7d340f5b912a
"""
from alembic import op
import sqlalchemy as sa

revision = "b4e0c019a624"
down_revision = "7d340f5b912a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("upload_tickets", sa.Column("quarantine_cleaned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("upload_tickets", sa.Column("processing_brand_id", sa.String(36), nullable=True))
    op.add_column("upload_tickets", sa.Column("expected_sha256", sa.String(64), nullable=True))
    op.add_column("upload_tickets", sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("upload_tickets", sa.Column("processing_error", sa.Text(), nullable=True))
    op.add_column("upload_tickets", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("upload_tickets", sa.Column("lease_token", sa.String(36), nullable=True))
    op.add_column("upload_tickets", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_upload_tickets_dispatch", "upload_tickets", ["status", "next_attempt_at"])
    op.create_index("ix_upload_tickets_leases", "upload_tickets", ["status", "lease_expires_at"])
    op.create_index("ix_upload_tickets_cleanup", "upload_tickets", ["status", "quarantine_cleaned_at", "updated_at"])
    op.create_index("ix_campaigns_expiry", "campaigns", ["status", "end_time"])
    op.create_index("ix_enrollment_challenges_expiry", "enrollment_challenges", ["status", "expires_at"])


def downgrade():
    op.drop_index("ix_enrollment_challenges_expiry", table_name="enrollment_challenges")
    op.drop_index("ix_campaigns_expiry", table_name="campaigns")
    for name in ("ix_upload_tickets_cleanup", "ix_upload_tickets_leases", "ix_upload_tickets_dispatch"):
        op.drop_index(name, table_name="upload_tickets")
    with op.batch_alter_table("upload_tickets") as batch:
        for column in ("lease_expires_at", "lease_token", "next_attempt_at", "processing_error",
                       "processing_attempts", "expected_sha256", "processing_brand_id", "quarantine_cleaned_at"):
            batch.drop_column(column)
