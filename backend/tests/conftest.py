import os
import subprocess
import sys

os.environ.update(
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://mosi:mosi@localhost:5432/mosi_test"),
    SECRET_KEY="test-secret-key-for-unit-tests",
    TESTING="true",
    DISABLE_JOBS="true",
    COOKIE_SECURE="false",
    HERMES_ENABLED="false",
    MCP_TOKEN="test-mcp-token",
    PUBLIC_URL="https://mosi.test",
    DATA_DIR=os.environ.get("TEST_DATA_DIR", "/tmp/mosi-test-data"),
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    from app.db import engine

    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    # Migrationen wie im Betrieb ausführen (prüft gleichzeitig die Migrationen)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True, env=os.environ.copy())
    yield


@pytest.fixture(autouse=True)
def clean_db(migrated_db):
    from app.db import engine
    from app.security import limiter

    tables = ["weekly_plan_items", "weekly_plans", "pending_actions", "messages", "conversations", "memory_entries", "calendar_events",
              "google_calendars", "categories", "tasks", "projects", "notifications", "push_subscriptions", "audit_log", "user_sessions", "app_settings", "users"]
    with engine.begin() as c:
        c.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    limiter._hits.clear()
    yield


@pytest.fixture
def db():
    from app.db import SessionLocal

    s = SessionLocal()
    yield s
    s.close()


PASSWORD = "Sicher-Passwort-2026"


@pytest.fixture
def user(db):
    from app.models import User
    from app.security import hash_password

    u = User(username="mosi", password_hash=hash_password(PASSWORD), display_name="Mo", timezone="Europe/Berlin")
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def anon():
    from app.main import app

    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def client(anon, user):
    r = anon.post("/api/auth/login", json={"username": "mosi", "password": PASSWORD})
    assert r.status_code == 200, r.text
    anon.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return anon
