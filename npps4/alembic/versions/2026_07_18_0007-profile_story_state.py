"""isolate event and multi-unit story state by client profile

Revision ID: profile_story_state
Revises: dual_client_profiles
Create Date: 2026-07-18 16:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from npps4.config import config as npps4_config

revision: str = "profile_story_state"
down_revision: Union[str, None] = "dual_client_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IDInteger = sa.BigInteger().with_variant(sa.INTEGER(), "sqlite")


def _sqlite_upgrade(table: str, id_column: str, default_profile: str) -> None:
    temp = f"{table}__profile_new"
    op.execute(
        sa.text(
            f'''CREATE TABLE "{temp}" (
                id INTEGER NOT NULL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                profile VARCHAR NOT NULL,
                {id_column} INTEGER NOT NULL,
                completed BOOLEAN NOT NULL,
                is_new BOOLEAN NOT NULL,
                insert_date INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES user(id),
                UNIQUE(user_id, profile, {id_column})
            )'''
        )
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f'''INSERT INTO "{temp}"
                (id, user_id, profile, {id_column}, completed, is_new, insert_date)
                SELECT id, user_id, :profile, {id_column}, completed, is_new, insert_date
                  FROM "{table}"'''
        ),
        {"profile": default_profile},
    )
    op.execute(sa.text(f'DROP TABLE "{table}"'))
    op.execute(sa.text(f'ALTER TABLE "{temp}" RENAME TO "{table}"'))
    op.create_index(f"ix_{table}_user_id", table, ["user_id"], unique=False)
    op.create_index(f"ix_{table}_profile", table, ["profile"], unique=False)
    op.create_index(f"ix_{table}_{id_column}", table, [id_column], unique=False)
    op.create_index(f"ix_{table}_completed", table, ["completed"], unique=False)
    op.create_index(f"ix_{table}_is_new", table, ["is_new"], unique=False)
    op.create_index(f"ix_{table}_insert_date", table, ["insert_date"], unique=False)


def _non_sqlite_upgrade(table: str, id_column: str, default_profile: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = inspector.get_unique_constraints(table)
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile", sa.String(), nullable=False, server_default=default_profile))
        for constraint in constraints:
            if set(constraint.get("column_names") or ()) == {"user_id", id_column}:
                name = constraint.get("name")
                if name:
                    batch_op.drop_constraint(name, type_="unique")
        batch_op.create_unique_constraint(f"uq_{table}_user_profile_{id_column}", ["user_id", "profile", id_column])
        batch_op.create_index(f"ix_{table}_profile", ["profile"], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    default_profile = npps4_config.get_default_profile().value
    for table, id_column in (
        ("event_scenario_unlock", "event_scenario_id"),
        ("multi_unit_scenario_unlock", "multi_unit_scenario_id"),
    ):
        if bind.dialect.name == "sqlite":
            _sqlite_upgrade(table, id_column, default_profile)
        else:
            _non_sqlite_upgrade(table, id_column, default_profile)


def _sqlite_downgrade(table: str, id_column: str, default_profile: str) -> None:
    temp = f"{table}__legacy_new"
    op.execute(
        sa.text(
            f'''CREATE TABLE "{temp}" (
                id INTEGER NOT NULL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                {id_column} INTEGER NOT NULL,
                completed BOOLEAN NOT NULL,
                is_new BOOLEAN NOT NULL,
                insert_date INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES user(id),
                UNIQUE(user_id, {id_column})
            )'''
        )
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f'''INSERT INTO "{temp}"
                (id, user_id, {id_column}, completed, is_new, insert_date)
                SELECT id, user_id, {id_column}, completed, is_new, insert_date
                  FROM "{table}"
                 WHERE profile = :profile'''
        ),
        {"profile": default_profile},
    )
    op.execute(sa.text(f'DROP TABLE "{table}"'))
    op.execute(sa.text(f'ALTER TABLE "{temp}" RENAME TO "{table}"'))
    op.create_index(f"ix_{table}_user_id", table, ["user_id"], unique=False)
    op.create_index(f"ix_{table}_{id_column}", table, [id_column], unique=False)
    op.create_index(f"ix_{table}_completed", table, ["completed"], unique=False)
    op.create_index(f"ix_{table}_is_new", table, ["is_new"], unique=False)
    op.create_index(f"ix_{table}_insert_date", table, ["insert_date"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    default_profile = npps4_config.get_default_profile().value
    for table, id_column in (
        ("event_scenario_unlock", "event_scenario_id"),
        ("multi_unit_scenario_unlock", "multi_unit_scenario_id"),
    ):
        if bind.dialect.name == "sqlite":
            _sqlite_downgrade(table, id_column, default_profile)
        else:
            inspector = sa.inspect(bind)
            constraints = inspector.get_unique_constraints(table)
            with op.batch_alter_table(table, schema=None) as batch_op:
                for constraint in constraints:
                    if set(constraint.get("column_names") or ()) == {"user_id", "profile", id_column}:
                        name = constraint.get("name")
                        if name:
                            batch_op.drop_constraint(name, type_="unique")
                batch_op.drop_index(f"ix_{table}_profile")
                batch_op.drop_column("profile")
                batch_op.create_unique_constraint(f"uq_{table}_user_{id_column}", ["user_id", id_column])
