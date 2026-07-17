"""cn accessories

Revision ID: cn_accessories
Revises: cn_user_greets
Create Date: 2026-06-30 00:03:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cn_accessories"
down_revision: Union[str, None] = "cn_user_greets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IDInteger = sa.BigInteger().with_variant(sa.INTEGER(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "user_accessory",
        sa.Column("id", IDInteger, primary_key=True, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("accessory_id", IDInteger, nullable=False),
        sa.Column("exp", IDInteger, nullable=False),
        sa.Column("favorite_flag", sa.Boolean(), nullable=False),
        sa.Column("insert_date", IDInteger, nullable=False),
        sa.Column("update_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
    )
    op.create_index(op.f("ix_user_accessory_user_id"), "user_accessory", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_accessory_accessory_id"), "user_accessory", ["accessory_id"], unique=False)
    op.create_index(op.f("ix_user_accessory_favorite_flag"), "user_accessory", ["favorite_flag"], unique=False)
    op.create_index(op.f("ix_user_accessory_insert_date"), "user_accessory", ["insert_date"], unique=False)
    op.create_index(op.f("ix_user_accessory_update_date"), "user_accessory", ["update_date"], unique=False)

    op.create_table(
        "user_accessory_wear",
        sa.Column("id", IDInteger, primary_key=True, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("unit_owning_user_id", IDInteger, nullable=False),
        sa.Column("accessory_owning_user_id", IDInteger, nullable=False),
        sa.Column("insert_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["unit_owning_user_id"], ["unit.id"]),
        sa.ForeignKeyConstraint(["accessory_owning_user_id"], ["user_accessory.id"]),
        sa.UniqueConstraint("user_id", "unit_owning_user_id"),
        sa.UniqueConstraint("user_id", "accessory_owning_user_id"),
    )
    op.create_index(op.f("ix_user_accessory_wear_user_id"), "user_accessory_wear", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_accessory_wear_unit_owning_user_id"), "user_accessory_wear", ["unit_owning_user_id"], unique=False)
    op.create_index(op.f("ix_user_accessory_wear_accessory_owning_user_id"), "user_accessory_wear", ["accessory_owning_user_id"], unique=False)
    op.create_index(op.f("ix_user_accessory_wear_insert_date"), "user_accessory_wear", ["insert_date"], unique=False)

    op.create_table(
        "user_accessory_material",
        sa.Column("id", IDInteger, primary_key=True, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("accessory_id", IDInteger, nullable=False),
        sa.Column("amount", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("user_id", "accessory_id"),
    )
    op.create_index(op.f("ix_user_accessory_material_user_id"), "user_accessory_material", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_accessory_material_accessory_id"), "user_accessory_material", ["accessory_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_accessory_material_accessory_id"), table_name="user_accessory_material")
    op.drop_index(op.f("ix_user_accessory_material_user_id"), table_name="user_accessory_material")
    op.drop_table("user_accessory_material")

    op.drop_index(op.f("ix_user_accessory_wear_insert_date"), table_name="user_accessory_wear")
    op.drop_index(op.f("ix_user_accessory_wear_accessory_owning_user_id"), table_name="user_accessory_wear")
    op.drop_index(op.f("ix_user_accessory_wear_unit_owning_user_id"), table_name="user_accessory_wear")
    op.drop_index(op.f("ix_user_accessory_wear_user_id"), table_name="user_accessory_wear")
    op.drop_table("user_accessory_wear")

    op.drop_index(op.f("ix_user_accessory_update_date"), table_name="user_accessory")
    op.drop_index(op.f("ix_user_accessory_insert_date"), table_name="user_accessory")
    op.drop_index(op.f("ix_user_accessory_favorite_flag"), table_name="user_accessory")
    op.drop_index(op.f("ix_user_accessory_accessory_id"), table_name="user_accessory")
    op.drop_index(op.f("ix_user_accessory_user_id"), table_name="user_accessory")
    op.drop_table("user_accessory")
