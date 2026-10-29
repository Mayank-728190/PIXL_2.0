from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pixl.core.database import Base, UUIDPrimaryKeyMixin, TimestampMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    organization_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # master_admin, agency_admin, agency_operator, brand_advertiser
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)  # ACTIVE, INVITED, SUSPENDED, DELETED

    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_totp_counter: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="users")


class UserInvitation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_invitations"

    organization_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_events"

    organization_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

