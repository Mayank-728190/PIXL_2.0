from sqlalchemy import String, Integer, BigInteger, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, Optional

from pixl.core.database import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)  # ACTIVE, SUSPENDED, DELETED
    max_screens: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    storage_quota_bytes: Mapped[int] = mapped_column(BigInteger, default=53687091200, nullable=False)  # 50 GB default

    users: Mapped[List["User"]] = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    sites: Mapped[List["Site"]] = relationship("Site", back_populates="organization", cascade="all, delete-orphan")
    brands: Mapped[List["Brand"]] = relationship("Brand", back_populates="organization", cascade="all, delete-orphan")
    screens: Mapped[List["Screen"]] = relationship("Screen", back_populates="organization", cascade="all, delete-orphan")


class Site(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sites"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="sites")
    screens: Mapped[List["Screen"]] = relationship("Screen", back_populates="site")


class Brand(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "brands"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="brands")

