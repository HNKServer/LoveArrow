"""isolate Museum unlock state by client profile

Revision ID: profile_museum_state
Revises: profile_story_state
Create Date: 2026-07-22 10:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from npps4.config import config as npps4_config

revision: str = "profile_museum_state"
down_revision: Union[str, None] = "profile_story_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sqlite_upgrade(default_profile: str) -> None:
    op.execute(sa.text('''CREATE TABLE "museum_unlock__profile_new" (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        profile VARCHAR NOT NULL,
        museum_contents_id INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES user(id),
        UNIQUE(user_id, profile, museum_contents_id)
    )'''))
    bind = op.get_bind()
    # Legacy rows were shared by CN and GL, so their original profile cannot be
    # reconstructed. Preserve the old semantics by copying every unlock into
    # both native-profile state sets. The active Master DB still filters out IDs
    # which are not native to the receiving profile.
    for profile in ("cn", "gl"):
        bind.execute(
            sa.text('''INSERT INTO "museum_unlock__profile_new"
                (user_id, profile, museum_contents_id)
                SELECT user_id, :profile, museum_contents_id FROM museum_unlock'''),
            {"profile": profile},
        )
    op.execute(sa.text('DROP TABLE museum_unlock'))
    op.execute(sa.text('ALTER TABLE "museum_unlock__profile_new" RENAME TO museum_unlock'))
    op.create_index("ix_museum_unlock_user_id", "museum_unlock", ["user_id"], unique=False)
    op.create_index("ix_museum_unlock_profile", "museum_unlock", ["profile"], unique=False)
    op.create_index("ix_museum_unlock_museum_contents_id", "museum_unlock", ["museum_contents_id"], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    default_profile = npps4_config.get_default_profile().value
    if bind.dialect.name == "sqlite":
        _sqlite_upgrade(default_profile)
        return

    inspector = sa.inspect(bind)
    constraints = inspector.get_unique_constraints("museum_unlock")
    with op.batch_alter_table("museum_unlock", schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile", sa.String(), nullable=False, server_default=default_profile))
        for constraint in constraints:
            if set(constraint.get("column_names") or ()) == {"user_id", "museum_contents_id"}:
                if constraint.get("name"):
                    batch_op.drop_constraint(constraint["name"], type_="unique")
        batch_op.create_unique_constraint(
            "uq_museum_unlock_user_profile_contents",
            ["user_id", "profile", "museum_contents_id"],
        )
        batch_op.create_index("ix_museum_unlock_profile", ["profile"], unique=False)

    # As above, the legacy schema did not record a region. Keep every historic
    # unlock visible in normal mode for both profiles rather than arbitrarily
    # assigning it to whichever profile is configured as default at upgrade time.
    for profile in ("cn", "gl"):
        if profile == default_profile:
            continue
        bind.execute(
            sa.text('''INSERT INTO museum_unlock
                (user_id, profile, museum_contents_id)
                SELECT user_id, :profile, museum_contents_id
                  FROM museum_unlock WHERE profile = :default_profile'''),
            {"profile": profile, "default_profile": default_profile},
        )


def downgrade() -> None:
    bind = op.get_bind()
    default_profile = npps4_config.get_default_profile().value
    if bind.dialect.name == "sqlite":
        op.execute(sa.text('''CREATE TABLE "museum_unlock__legacy_new" (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            museum_contents_id INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES user(id),
            UNIQUE(user_id, museum_contents_id)
        )'''))
        bind.execute(
            sa.text('''INSERT INTO "museum_unlock__legacy_new"
                (id, user_id, museum_contents_id)
                SELECT id, user_id, museum_contents_id
                  FROM museum_unlock WHERE profile = :profile'''),
            {"profile": default_profile},
        )
        op.execute(sa.text('DROP TABLE museum_unlock'))
        op.execute(sa.text('ALTER TABLE "museum_unlock__legacy_new" RENAME TO museum_unlock'))
        op.create_index("ix_museum_unlock_user_id", "museum_unlock", ["user_id"], unique=False)
        op.create_index("ix_museum_unlock_museum_contents_id", "museum_unlock", ["museum_contents_id"], unique=False)
        return

    with op.batch_alter_table("museum_unlock", schema=None) as batch_op:
        batch_op.drop_index("ix_museum_unlock_profile")
        batch_op.drop_column("profile")
        batch_op.create_unique_constraint(
            "uq_museum_unlock_user_contents", ["user_id", "museum_contents_id"]
        )
