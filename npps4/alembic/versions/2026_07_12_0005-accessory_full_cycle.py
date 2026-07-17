"""complete accessory lifecycle state

Revision ID: accessory_full_cycle
Revises: cn_post_service_content
Create Date: 2026-07-12 06:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "accessory_full_cycle"
down_revision: Union[str, None] = "cn_post_service_content"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IDInteger = sa.BigInteger().with_variant(sa.INTEGER(), "sqlite")


def upgrade() -> None:
    with op.batch_alter_table("user_accessory", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rank_up_count", IDInteger, nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("user_accessory", schema=None) as batch_op:
        batch_op.drop_column("rank_up_count")
