from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .constants import IMAGE_DIM, TEXT_DIM
from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, always returns timezone-aware UTC (works on Postgres and SQLite)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class EmbeddingVector(TypeDecorator):
    """pgvector `vector(dim)` on PostgreSQL, JSON list elsewhere (lets tests run on SQLite)."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    items: Mapped[list["Item"]] = relationship(back_populates="owner")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(8), index=True)  # lost | found
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    location_text: Mapped[str] = mapped_column(String(200))
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    date_event: Mapped[date] = mapped_column(Date, index=True)
    distinguishing_features: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Hidden detail (serial number, contents...) only the owner can read; used to verify claims.
    private_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)

    owner: Mapped["User"] = relationship(back_populates="items")
    embedding: Mapped[Optional["ItemEmbedding"]] = relationship(
        back_populates="item", uselist=False, cascade="all, delete-orphan"
    )


class ItemEmbedding(Base):
    __tablename__ = "item_embeddings"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    image_vec: Mapped[Optional[list[float]]] = mapped_column(EmbeddingVector(IMAGE_DIM), nullable=True)
    text_vec: Mapped[Optional[list[float]]] = mapped_column(EmbeddingVector(TEXT_DIM), nullable=True)
    # Vectors from different backends live in different spaces and must never be compared.
    backend: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    item: Mapped["Item"] = relationship(back_populates="embedding")


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("lost_item_id", "found_item_id", name="uq_match_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lost_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    found_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    image_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-100
    text_score: Mapped[float] = mapped_column(Float)  # 0-100
    location_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-100
    location_label: Mapped[str] = mapped_column(String(24), default="Unknown")
    days_apart: Mapped[int] = mapped_column(Integer, default=0)
    final_score: Mapped[float] = mapped_column(Float, index=True)  # 0-100
    explanation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="suggested")  # suggested | dismissed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    lost_item: Mapped["Item"] = relationship(foreign_keys=[lost_item_id])
    found_item: Mapped["Item"] = relationship(foreign_keys=[found_item_id])


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    claimant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)  # the report being claimed
    lost_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("items.id"), nullable=True)  # claimant's own report
    message: Mapped[str] = mapped_column(Text)
    verification_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    claimant: Mapped["User"] = relationship()
    item: Mapped["Item"] = relationship(foreign_keys=[item_id])
    lost_item: Mapped[Optional["Item"]] = relationship(foreign_keys=[lost_item_id])
