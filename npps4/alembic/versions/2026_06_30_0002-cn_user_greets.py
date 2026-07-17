"""cn user greets

Revision ID: cn_user_greets
Revises: cn_friend_links
Create Date: 2026-06-30 00:02:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cn_user_greets"
down_revision: Union[str, None] = "cn_friend_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_greet",
        sa.Column("id", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), primary_key=True, nullable=False),
        sa.Column("affector_id", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), nullable=False),
        sa.Column("receiver_id", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("reply", sa.Boolean(), nullable=False),
        sa.Column("readed", sa.Boolean(), nullable=False),
        sa.Column("deleted_from_affector", sa.Boolean(), nullable=False),
        sa.Column("deleted_from_receiver", sa.Boolean(), nullable=False),
        sa.Column("insert_date", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), nullable=False),
        sa.ForeignKeyConstraint(["affector_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["receiver_id"], ["user.id"]),
    )
    op.create_index(op.f("ix_user_greet_affector_id"), "user_greet", ["affector_id"], unique=False)
    op.create_index(op.f("ix_user_greet_receiver_id"), "user_greet", ["receiver_id"], unique=False)
    op.create_index(op.f("ix_user_greet_readed"), "user_greet", ["readed"], unique=False)
    op.create_index(op.f("ix_user_greet_deleted_from_affector"), "user_greet", ["deleted_from_affector"], unique=False)
    op.create_index(op.f("ix_user_greet_deleted_from_receiver"), "user_greet", ["deleted_from_receiver"], unique=False)
    op.create_index(op.f("ix_user_greet_insert_date"), "user_greet", ["insert_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_greet_insert_date"), table_name="user_greet")
    op.drop_index(op.f("ix_user_greet_deleted_from_receiver"), table_name="user_greet")
    op.drop_index(op.f("ix_user_greet_deleted_from_affector"), table_name="user_greet")
    op.drop_index(op.f("ix_user_greet_readed"), table_name="user_greet")
    op.drop_index(op.f("ix_user_greet_receiver_id"), table_name="user_greet")
    op.drop_index(op.f("ix_user_greet_affector_id"), table_name="user_greet")
    op.drop_table("user_greet")
