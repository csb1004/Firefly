from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://") and "+" not in url.split(":", 1)[0]:
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def build_engine(url: str | None = None) -> Engine:
    resolved = normalize_database_url(url or settings.database_url)
    kwargs = {"pool_pre_ping": True}
    if resolved.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(resolved, **kwargs)
    if resolved.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


DEFAULT_RARITY_PROBABILITIES = {
    1: 45.0,
    2: 30.0,
    3: 19.3,
    4: 5.1,
    5: 0.6,
}


def init_database(target_engine: Engine | None = None) -> None:
    from .models import Base, DrawSetting, RaritySetting

    active_engine = target_engine or engine
    Base.metadata.create_all(active_engine)
    with Session(active_engine) as db:
        existing = set(db.scalars(select(RaritySetting.rarity)).all())
        for rarity, probability in DEFAULT_RARITY_PROBABILITIES.items():
            if rarity not in existing:
                db.add(RaritySetting(rarity=rarity, probability=probability))
        if db.get(DrawSetting, 1) is None:
            db.add(DrawSetting(id=1, daily_draws=1))
        db.commit()
