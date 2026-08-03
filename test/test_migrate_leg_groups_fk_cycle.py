"""
Regression test for upgrade/migrate_sqlite_to_postgres.py's handling of the
genuine circular foreign key between leg_groups and legs
(LegGroup.current_leg_id -> legs.id, Leg.leg_group_id -> leg_groups.id --
see database/strategy_db.py's LegGroup/Leg docstrings for why this cycle is
intentional, not a modeling bug).

Root cause this covers: MetaData.sorted_tables cannot linearize a real
cycle -- it emits a SAWarning and drops BOTH tables' FK constraints from
ordering consideration, which the migration script used to trust blindly.
Naively copying leg_groups rows with a non-NULL current_leg_id before the
referenced legs row exists would violate the FK on any backend that
actually enforces it (confirmed: SQLite only enforces FKs when
`PRAGMA foreign_keys=ON` is set -- which is exactly why this bug could
survive undetected against a SQLite source/dev environment and only
surface as a hard failure against Postgres, which always enforces FKs).

This test uses two real SQLite files (source + destination) with FK
enforcement turned ON for the destination connection, so it genuinely
proves the null-then-backfill approach works under real constraint
checking -- not just that no exception happens to be raised.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import (  # noqa: E402
    Boolean,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.orm import declarative_base  # noqa: E402

from upgrade.migrate_sqlite_to_postgres import (  # noqa: E402
    _DEFER_FK_COLUMN,
    apply_deferred_backfill,
    copy_table,
)

Base = declarative_base()


class LegGroup(Base):
    __tablename__ = "leg_groups"
    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    current_leg_id = Column(Integer, ForeignKey("legs.id"), nullable=True)


class Leg(Base):
    __tablename__ = "legs"
    id = Column(Integer, primary_key=True)
    leg_group_id = Column(Integer, ForeignKey("leg_groups.id"), nullable=False)
    label = Column(String(50), nullable=False)


@pytest.fixture
def source_engine():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "source.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        with engine.begin() as conn:
            # A leg group with an open leg: current_leg_id references a
            # legs row that (in insertion-order terms) doesn't exist yet if
            # you tried to insert leg_groups before legs -- this is exactly
            # the scenario that would break without the deferred-column fix.
            conn.execute(LegGroup.__table__.insert(), [{"id": 1, "strategy_id": 100, "name": "Call/Put", "is_active": True, "current_leg_id": None}])
            conn.execute(Leg.__table__.insert(), [
                {"id": 1, "leg_group_id": 1, "label": "Call"},
                {"id": 2, "leg_group_id": 1, "label": "Put"},
            ])
            # Now set current_leg_id -- this is the state a real running
            # strategy would be in: leg_group 1's currently-open leg is leg 1.
            conn.execute(LegGroup.__table__.update().where(LegGroup.id == 1).values(current_leg_id=1))

        yield engine
        engine.dispose()


@pytest.fixture
def dest_engine():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "dest.db"
        engine = create_engine(f"sqlite:///{db_path}")

        # Turn ON real FK enforcement for every connection to this engine --
        # SQLite does NOT enforce FKs by default, which is precisely why
        # this bug could pass silently against a SQLite destination and only
        # bite for real against Postgres (always enforced). Enforcing here
        # makes this test a genuine proof, not a no-op.
        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


def test_leg_groups_legs_cycle_copies_without_fk_violation(source_engine, dest_engine):
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    tables = list(metadata.sorted_tables)

    # Mirror migrate_group's explicit reorder: leg_groups must physically
    # insert before legs regardless of whatever sorted_tables produced.
    lg_idx = next(i for i, t in enumerate(tables) if t.name == "leg_groups")
    leg_idx = next(i for i, t in enumerate(tables) if t.name == "legs")
    if lg_idx > leg_idx:
        tables[lg_idx], tables[leg_idx] = tables[leg_idx], tables[lg_idx]

    source_tables = set(inspect(source_engine).get_table_names())

    pending_backfills = []
    for table in tables:
        src_count, copied, deferred_values = copy_table(
            table, source_engine, dest_engine, truncate_first=False, dry_run=False, source_tables=source_tables
        )
        assert src_count == copied, f"{table.name}: expected all {src_count} rows copied, got {copied}"
        if deferred_values:
            pending_backfills.append((table, _DEFER_FK_COLUMN[table.name], deferred_values))

    for table, defer_col, deferred_values in pending_backfills:
        apply_deferred_backfill(table, dest_engine, defer_col, deferred_values)

    with dest_engine.connect() as conn:
        leg_groups_rows = conn.execute(LegGroup.__table__.select()).mappings().all()
        legs_rows = conn.execute(Leg.__table__.select()).mappings().all()

    assert len(leg_groups_rows) == 1
    assert len(legs_rows) == 2

    # The real proof: current_leg_id was correctly backfilled to 1 after
    # both tables were populated -- not left NULL (which would silently
    # corrupt the migrated data even though no FK violation occurred).
    assert leg_groups_rows[0]["current_leg_id"] == 1


def test_deferred_value_of_none_is_left_alone(source_engine, dest_engine):
    """A leg_group that's currently flat (current_leg_id already NULL in
    the source) must stay NULL after migration -- not accidentally
    "backfilled" to something, since _DEFER_FK_COLUMN's dict only stashes
    non-NULL values (see copy_table: `if row.get(defer_col) is not None`)."""
    with source_engine.begin() as conn:
        conn.execute(LegGroup.__table__.insert(), [
            {"id": 2, "strategy_id": 200, "name": "Flat group", "is_active": True, "current_leg_id": None}
        ])

    metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    tables = list(metadata.sorted_tables)
    lg_idx = next(i for i, t in enumerate(tables) if t.name == "leg_groups")
    leg_idx = next(i for i, t in enumerate(tables) if t.name == "legs")
    if lg_idx > leg_idx:
        tables[lg_idx], tables[leg_idx] = tables[leg_idx], tables[lg_idx]

    source_tables = set(inspect(source_engine).get_table_names())
    pending_backfills = []
    for table in tables:
        _, _, deferred_values = copy_table(
            table, source_engine, dest_engine, truncate_first=False, dry_run=False, source_tables=source_tables
        )
        if deferred_values:
            pending_backfills.append((table, _DEFER_FK_COLUMN[table.name], deferred_values))

    for table, defer_col, deferred_values in pending_backfills:
        apply_deferred_backfill(table, dest_engine, defer_col, deferred_values)

    with dest_engine.connect() as conn:
        rows = conn.execute(
            LegGroup.__table__.select().where(LegGroup.id == 2)
        ).mappings().all()

    assert rows[0]["current_leg_id"] is None
