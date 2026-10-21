"""Verify the database connection end to end:  python -m app.db_check

Checks the connection, that pgvector is available, creates the extension/tables/indexes
(same as API startup) and prints row counts.
"""

import sys

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from .config import settings
from .database import SessionLocal, engine, init_db


def _safe_url() -> str:
    return engine.url.render_as_string(hide_password=True)


def main() -> int:
    print(f"Connecting to {_safe_url()} ...")
    try:
        with engine.connect() as conn:
            version = conn.execute(text("select version()")).scalar()
    except OperationalError as exc:
        print(f"FAILED: could not connect.\n  {str(exc.orig).strip()}")
        print("  Is Postgres running?  ->  docker compose up -d db")
        return 1
    print(f"  OK  {version}")

    if engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            available = conn.execute(text("select 1 from pg_available_extensions where name = 'vector'")).scalar()
        if not available:
            print("FAILED: the pgvector extension isn't installed on this server.")
            print("  Use the pgvector/pgvector:pg16 image (docker compose up -d db) or install pgvector.")
            return 1
        print("  OK  pgvector extension available")

    try:
        init_db()
    except ProgrammingError as exc:
        print(f"FAILED: could not create the schema.\n  {str(exc.orig).strip()}")
        return 1
    tables = sorted(inspect(engine).get_table_names())
    print(f"  OK  tables: {', '.join(tables)}")

    from .models import Claim, Item, ItemEmbedding, Match, User

    with SessionLocal() as db:
        for model in (User, Item, ItemEmbedding, Match, Claim):
            count = db.scalar(select(func.count()).select_from(model))
            print(f"      {model.__tablename__:<16}{count} rows")
    print(f"Database ready. Embedding backend: {settings.embedding_backend}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
