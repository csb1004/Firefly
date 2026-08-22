import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("DISCORD_BOT_TOKEN", "test-discord-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


@pytest.fixture()
def web_db():
    from bandi_cards.db import init_database

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    init_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture()
def web_client(web_db):
    from bandi_cards.app import create_app
    from bandi_cards.db import get_db

    app = create_app()
    app.state.session_factory = web_db

    def override_db():
        db = web_db()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client


def _signed_in_fixture(web_client, web_db, discord_id, username, *, acknowledged):
    from datetime import timedelta

    from bandi_cards.models import User, WebSession, utcnow
    from bandi_cards.security import SESSION_COOKIE, csrf_token_for_session, random_token, token_hash

    raw_session = random_token()
    raw_csrf = csrf_token_for_session(raw_session)
    with web_db() as db:
        user = User(
            discord_id=discord_id,
            username=username,
            global_name="반디" if not acknowledged else None,
            warning_acknowledged=acknowledged,
        )
        db.add(user)
        db.flush()
        db.add(
            WebSession(
                token_hash=token_hash(raw_session),
                user_id=user.id,
                expires_at=utcnow() + timedelta(days=90),
            )
        )
        db.commit()
        user_id = user.id
    web_client.cookies.set(SESSION_COOKIE, raw_session)
    return web_client, web_db, user_id, raw_csrf


@pytest.fixture()
def signed_in(web_client, web_db):
    return _signed_in_fixture(web_client, web_db, "101010", "bandi", acknowledged=False)


@pytest.fixture()
def admin_signed_in(web_client, web_db):
    from bandi_cards.config import settings

    return _signed_in_fixture(
        web_client,
        web_db,
        str(settings.special_user_id),
        "admin",
        acknowledged=True,
    )

