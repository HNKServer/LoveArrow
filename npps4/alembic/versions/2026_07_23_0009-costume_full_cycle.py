"""profile-aware persistent costume full cycle

Revision ID: costume_full_cycle
Revises: profile_museum_state
Create Date: 2026-07-23 04:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "costume_full_cycle"
down_revision: Union[str, None] = "profile_museum_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IDInteger = sa.BigInteger().with_variant(sa.INTEGER(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "user_costume",
        sa.Column("id", IDInteger, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("unit_id", IDInteger, nullable=False),
        sa.Column("is_rank_max", sa.Boolean(), nullable=False),
        sa.Column("is_signed", sa.Boolean(), nullable=False),
        sa.Column("source_unit_owning_user_id", IDInteger, nullable=False),
        sa.Column("insert_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "profile", "unit_id", "is_signed"),
    )
    for column in ("user_id", "profile", "unit_id", "source_unit_owning_user_id", "insert_date"):
        op.create_index(op.f(f"ix_user_costume_{column}"), "user_costume", [column], unique=False)

    op.create_table(
        "user_costume_dress",
        sa.Column("id", IDInteger, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("unit_owning_user_id", IDInteger, nullable=False),
        sa.Column("costume_unit_id", IDInteger, nullable=False),
        sa.Column("is_rank_max", sa.Boolean(), nullable=False),
        sa.Column("is_signed", sa.Boolean(), nullable=False),
        sa.Column("insert_date", IDInteger, nullable=False),
        sa.Column("update_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["unit_owning_user_id"], ["unit.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "profile", "unit_owning_user_id"),
    )
    for column in ("user_id", "profile", "unit_owning_user_id", "costume_unit_id", "insert_date", "update_date"):
        op.create_index(op.f(f"ix_user_costume_dress_{column}"), "user_costume_dress", [column], unique=False)

    op.create_table(
        "user_costume_setting",
        sa.Column("id", IDInteger, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("update_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "profile"),
    )
    for column in ("user_id", "profile", "update_date"):
        op.create_index(op.f(f"ix_user_costume_setting_{column}"), "user_costume_setting", [column], unique=False)


def downgrade() -> None:
    for table, columns in (
        ("user_costume_setting", ("update_date", "profile", "user_id")),
        ("user_costume_dress", ("update_date", "insert_date", "costume_unit_id", "unit_owning_user_id", "profile", "user_id")),
        ("user_costume", ("insert_date", "source_unit_owning_user_id", "unit_id", "profile", "user_id")),
    ):
        for column in columns:
            op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
        op.drop_table(table)
