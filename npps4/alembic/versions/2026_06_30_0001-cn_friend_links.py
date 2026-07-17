"""add shared friend links for CN/global interop

Revision ID: cn_friend_links
Revises: b3d6a058fa62
Create Date: 2026-06-30 00:01:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "cn_friend_links"
down_revision: Union[str, None] = "b3d6a058fa62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "friend_link",
        sa.Column("id", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), primary_key=True, nullable=False),
        sa.Column("user_id", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), nullable=False),
        sa.Column("friend_user_id", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("insert_date", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), nullable=False),
        sa.Column("update_date", sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["friend_user_id"], ["user.id"]),
        sa.UniqueConstraint("user_id", "friend_user_id"),
    )
    op.create_index(op.f("ix_friend_link_user_id"), "friend_link", ["user_id"], unique=False)
    op.create_index(op.f("ix_friend_link_friend_user_id"), "friend_link", ["friend_user_id"], unique=False)
    op.create_index(op.f("ix_friend_link_status"), "friend_link", ["status"], unique=False)
    op.create_index(op.f("ix_friend_link_is_new"), "friend_link", ["is_new"], unique=False)
    op.create_index(op.f("ix_friend_link_insert_date"), "friend_link", ["insert_date"], unique=False)
    op.create_index(op.f("ix_friend_link_update_date"), "friend_link", ["update_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_friend_link_update_date"), table_name="friend_link")
    op.drop_index(op.f("ix_friend_link_insert_date"), table_name="friend_link")
    op.drop_index(op.f("ix_friend_link_is_new"), table_name="friend_link")
    op.drop_index(op.f("ix_friend_link_status"), table_name="friend_link")
    op.drop_index(op.f("ix_friend_link_friend_user_id"), table_name="friend_link")
    op.drop_index(op.f("ix_friend_link_user_id"), table_name="friend_link")
    op.drop_table("friend_link")
