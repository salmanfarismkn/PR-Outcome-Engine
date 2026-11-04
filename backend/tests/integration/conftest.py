from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session
from dotenv import dotenv_values

TEST_DATABASE_ENV = "PR_OUTCOME_ENGINE_TEST_DATABASE_URL"
DEVELOPMENT_DATABASE_URL = (
    os.getenv("DATABASE_URL", "").strip()
    or str(dotenv_values(".env").get("DATABASE_URL", "")).strip()
)


test_database_url = os.getenv(TEST_DATABASE_ENV, "").strip()
if test_database_url:
    os.environ["DATABASE_URL"] = test_database_url


def _test_database_url() -> str:
    value = os.getenv(TEST_DATABASE_ENV, "").strip()
    if not value:
        pytest.skip(
            f"{TEST_DATABASE_ENV} is not set; PostgreSQL integration tests "
            "require an explicitly configured dedicated database."
        )

    url = make_url(value)
    if url.drivername != "postgresql+psycopg":
        pytest.fail(
            f"{TEST_DATABASE_ENV} must use the postgresql+psycopg scheme."
        )

    development_url = DEVELOPMENT_DATABASE_URL
    if development_url and value == development_url:
        pytest.fail(
            f"{TEST_DATABASE_ENV} must not equal DATABASE_URL; use a "
            "dedicated integration database."
        )

    if not url.database:
        pytest.fail(f"{TEST_DATABASE_ENV} must include a database name.")
    return value


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    engine = create_engine(_test_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            required_columns = {
                row[0]
                for row in connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'webhook_event'
                        """
                    )
                )
            }
            required = {
                "delivery_id",
                "status",
                "attempt_count",
                "last_attempt_at",
                "last_error_at",
            }
            missing = required - required_columns
            if missing:
                pytest.fail(
                    "PostgreSQL database is reachable but not migrated to "
                    f"head; missing webhook_event columns: {sorted(missing)}"
                )
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def postgres_session(postgres_engine: Engine) -> Iterator[Session]:
    with Session(postgres_engine) as session:
        yield session


@pytest.fixture
def cleanup_webhook_events(postgres_engine: Engine):
    delivery_ids: list[str] = []
    yield delivery_ids
    if delivery_ids:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM webhook_event "
                    "WHERE delivery_id = ANY(:delivery_ids)"
                ),
                {"delivery_ids": delivery_ids},
            )
