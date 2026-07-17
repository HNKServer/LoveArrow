"""CN post-service content access state

Revision ID: cn_post_service_content
Revises: cn_accessories
Create Date: 2026-07-11 19:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "cn_post_service_content"
down_revision: Union[str, None] = "cn_accessories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IDInteger = sa.BigInteger().with_variant(sa.INTEGER(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "event_scenario_unlock",
        sa.Column("id", IDInteger, primary_key=True, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("event_scenario_id", IDInteger, nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("insert_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("user_id", "event_scenario_id"),
    )
    op.create_index(op.f("ix_event_scenario_unlock_user_id"), "event_scenario_unlock", ["user_id"])
    op.create_index(
        op.f("ix_event_scenario_unlock_event_scenario_id"),
        "event_scenario_unlock",
        ["event_scenario_id"],
    )
    op.create_index(op.f("ix_event_scenario_unlock_completed"), "event_scenario_unlock", ["completed"])
    op.create_index(op.f("ix_event_scenario_unlock_is_new"), "event_scenario_unlock", ["is_new"])
    op.create_index(op.f("ix_event_scenario_unlock_insert_date"), "event_scenario_unlock", ["insert_date"])

    op.create_table(
        "multi_unit_scenario_unlock",
        sa.Column("id", IDInteger, primary_key=True, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("multi_unit_scenario_id", IDInteger, nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("insert_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("user_id", "multi_unit_scenario_id"),
    )
    op.create_index(op.f("ix_multi_unit_scenario_unlock_user_id"), "multi_unit_scenario_unlock", ["user_id"])
    op.create_index(
        op.f("ix_multi_unit_scenario_unlock_multi_unit_scenario_id"),
        "multi_unit_scenario_unlock",
        ["multi_unit_scenario_id"],
    )
    op.create_index(op.f("ix_multi_unit_scenario_unlock_completed"), "multi_unit_scenario_unlock", ["completed"])
    op.create_index(op.f("ix_multi_unit_scenario_unlock_is_new"), "multi_unit_scenario_unlock", ["is_new"])
    op.create_index(op.f("ix_multi_unit_scenario_unlock_insert_date"), "multi_unit_scenario_unlock", ["insert_date"])

    op.create_table(
        "content_access_grant",
        sa.Column("id", IDInteger, primary_key=True, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("grant_key", sa.String(), nullable=False),
        sa.Column("grant_version", sa.Integer(), nullable=False),
        sa.Column("insert_date", IDInteger, nullable=False),
        sa.Column("update_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("user_id", "grant_key"),
    )
    op.create_index(op.f("ix_content_access_grant_user_id"), "content_access_grant", ["user_id"])
    op.create_index(op.f("ix_content_access_grant_grant_key"), "content_access_grant", ["grant_key"])
    op.create_index(op.f("ix_content_access_grant_insert_date"), "content_access_grant", ["insert_date"])
    op.create_index(op.f("ix_content_access_grant_update_date"), "content_access_grant", ["update_date"])


def downgrade() -> None:
    op.drop_index(op.f("ix_content_access_grant_update_date"), table_name="content_access_grant")
    op.drop_index(op.f("ix_content_access_grant_insert_date"), table_name="content_access_grant")
    op.drop_index(op.f("ix_content_access_grant_grant_key"), table_name="content_access_grant")
    op.drop_index(op.f("ix_content_access_grant_user_id"), table_name="content_access_grant")
    op.drop_table("content_access_grant")

    op.drop_index(op.f("ix_multi_unit_scenario_unlock_insert_date"), table_name="multi_unit_scenario_unlock")
    op.drop_index(op.f("ix_multi_unit_scenario_unlock_is_new"), table_name="multi_unit_scenario_unlock")
    op.drop_index(op.f("ix_multi_unit_scenario_unlock_completed"), table_name="multi_unit_scenario_unlock")
    op.drop_index(
        op.f("ix_multi_unit_scenario_unlock_multi_unit_scenario_id"),
        table_name="multi_unit_scenario_unlock",
    )
    op.drop_index(op.f("ix_multi_unit_scenario_unlock_user_id"), table_name="multi_unit_scenario_unlock")
    op.drop_table("multi_unit_scenario_unlock")

    op.drop_index(op.f("ix_event_scenario_unlock_insert_date"), table_name="event_scenario_unlock")
    op.drop_index(op.f("ix_event_scenario_unlock_is_new"), table_name="event_scenario_unlock")
    op.drop_index(op.f("ix_event_scenario_unlock_completed"), table_name="event_scenario_unlock")
    op.drop_index(
        op.f("ix_event_scenario_unlock_event_scenario_id"),
        table_name="event_scenario_unlock",
    )
    op.drop_index(op.f("ix_event_scenario_unlock_user_id"), table_name="event_scenario_unlock")
    op.drop_table("event_scenario_unlock")
