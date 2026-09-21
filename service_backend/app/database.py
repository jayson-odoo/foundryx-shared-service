"""Database configuration and session management."""
from typing import Dict, Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.config import settings


def worker_connect_args() -> Dict[str, str]:
    """Settings-driven Postgres session bounds (sprint-5/11 S1, AC-11-85).

    Every worker process (this same ``create_engine`` call, imported by both
    the API and every Celery worker) reads the SAME three settings; the
    settings themselves are 0/unset by default, so the API's behaviour is
    unchanged - only the compose worker services set the envs that make this
    return anything. Returns ``{}`` when all three are 0 (no ``connect_args``
    at all, today's behaviour exactly); otherwise a single Postgres
    ``options`` GUC string carrying only the non-zero timeouts, converted
    from settings-seconds to Postgres-milliseconds.
    """
    parts = []
    if settings.worker_db_statement_timeout_seconds:
        parts.append(
            f"-c statement_timeout={settings.worker_db_statement_timeout_seconds * 1000}"
        )
    if settings.worker_db_lock_timeout_seconds:
        parts.append(
            f"-c lock_timeout={settings.worker_db_lock_timeout_seconds * 1000}"
        )
    if settings.worker_db_idle_in_transaction_session_timeout_seconds:
        parts.append(
            "-c idle_in_transaction_session_timeout="
            f"{settings.worker_db_idle_in_transaction_session_timeout_seconds * 1000}"
        )
    if not parts:
        return {}
    return {"options": " ".join(parts)}


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=settings.debug,
    connect_args=worker_connect_args(),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session and ensure it is closed."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
