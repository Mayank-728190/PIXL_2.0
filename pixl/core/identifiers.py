"""Transactional numeric IDs for the legacy Android protocol."""
from sqlalchemy import BigInteger, String, case, func, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from pixl.core.database import Base


class NumberSequence(Base):
    __tablename__ = "number_sequences"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)


async def next_number(db, model, column_name, start):
    """Atomic upsert; the sequence increment commits with the owning object."""
    column = getattr(model, column_name)
    maximum = await db.scalar(select(func.max(column)))
    initial = max(maximum or 0, start) + 1
    dialect = db.get_bind().dialect.name
    insert = {"sqlite": sqlite_insert, "postgresql": pg_insert}.get(dialect)
    if insert is None:
        raise RuntimeError("Numeric IDs require SQLite or PostgreSQL")
    statement = insert(NumberSequence).values(name=model.__tablename__, value=initial)
    statement = statement.on_conflict_do_update(
        index_elements=[NumberSequence.name], set_={
            "value": case((NumberSequence.value < initial, initial), else_=NumberSequence.value + 1),
        },
    ).returning(NumberSequence.value)
    return (await db.execute(statement)).scalar_one()
