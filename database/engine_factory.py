"""Shared SQLAlchemy engine factory.

Centralizes engine creation so every database engine in the project follows the
same connection-pooling policy. This exists to enforce one rule across the whole
codebase, including all broker ``master_contract_db.py`` modules:

    All SQLite engines MUST use NullPool.

With NullPool each operation gets a fresh connection that is closed immediately
after use, so no file descriptors to the SQLite database file accumulate. A real
pool (the SQLAlchemy default QueuePool, or an explicit ``pool_size``/``max_overflow``)
holds connections open per worker thread and leaks descriptors over the lifetime
of the long-running Gunicorn/eventlet process.

StaticPool must NOT be used for SQLite: a single shared connection causes
"bad parameter or other API misuse" and "cannot commit - SQL statements in
progress" errors when concurrent requests corrupt the shared cursor state.

For non-SQLite backends (e.g. PostgreSQL) a normal connection pool is used.

SQLite pragmas (WAL journal mode, synchronous=NORMAL) are applied to every
connection process-wide by the listener in ``database/__init__.py`` — they do
not need to be set here.

See CLAUDE.md "SQLite Connection Pooling (NullPool)" and the reference
implementation in ``database/auth_db.py``.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def create_db_engine(
    database_url=None,
    echo=False,
    sqlite_connect_args=None,
    pool_size=None,
    max_overflow=None,
    pool_recycle=None,
):
    """Create a SQLAlchemy engine with the project-wide pooling policy.

    Args:
        database_url: SQLAlchemy database URL. Falls back to the ``DATABASE_URL``
            environment variable when not provided.
        echo: Passed straight through to ``create_engine`` (SQL statement logging).
        sqlite_connect_args: Extra ``connect_args`` merged in on top of
            ``check_same_thread=False`` when the resolved URL is SQLite (e.g.
            ``{"timeout": 30}``). Ignored for non-SQLite backends.
        pool_size: Override for the non-SQLite pool size. Falls back to the
            ``DB_POOL_SIZE`` env var (default 50) when not provided. Ignored
            for SQLite, which always uses NullPool.
        max_overflow: Override for the non-SQLite max overflow. Falls back to
            the ``DB_MAX_OVERFLOW`` env var (default 100) when not provided.
            Ignored for SQLite.
        pool_recycle: Optional ``pool_recycle`` (seconds) for the non-SQLite
            pool -- recycles a pooled connection after this many seconds to
            avoid the backend or an intermediary (e.g. a cloud DB proxy)
            silently dropping long-idle connections. Not set by default
            (SQLAlchemy's own default is -1 / no recycling). Ignored for
            SQLite.

    Returns:
        A configured SQLAlchemy ``Engine``. SQLite URLs use ``NullPool`` with
        ``check_same_thread=False``; other backends use a QueuePool.
    """
    database_url = database_url or os.getenv("DATABASE_URL")

    if database_url and "sqlite" in database_url:
        # SQLite: NullPool so each checkout creates a fresh connection that is
        # closed immediately. Session cleanup is handled by app.py
        # teardown_appcontext. StaticPool must NOT be used (see module docstring).
        connect_args = {"check_same_thread": False}
        if sqlite_connect_args:
            connect_args.update(sqlite_connect_args)
        return create_engine(
            database_url,
            echo=echo,
            poolclass=NullPool,
            connect_args=connect_args,
        )

    # Non-SQLite backends (e.g. PostgreSQL): use a real connection pool with pre-ping validation.
    kwargs = dict(
        echo=echo,
        pool_size=pool_size if pool_size is not None else int(os.getenv("DB_POOL_SIZE", "50")),
        max_overflow=max_overflow
        if max_overflow is not None
        else int(os.getenv("DB_MAX_OVERFLOW", "100")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
        pool_pre_ping=True,
    )
    if pool_recycle is not None:
        kwargs["pool_recycle"] = pool_recycle
    return create_engine(database_url, **kwargs)
