"""dual client profiles and persistent random live sessions

Revision ID: dual_client_profiles
Revises: accessory_full_cycle
Create Date: 2026-07-18 14:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from npps4.config import config as npps4_config

revision: str = "dual_client_profiles"
down_revision: Union[str, None] = "accessory_full_cycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IDInteger = sa.BigInteger().with_variant(sa.INTEGER(), "sqlite")


def upgrade() -> None:
    with op.batch_alter_table("session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile", sa.String(), nullable=False, server_default="gl"))
        batch_op.add_column(sa.Column("server_rsa_label", sa.String(), nullable=True))
        batch_op.create_index(batch_op.f("ix_session_profile"), ["profile"], unique=False)

    op.create_table(
        "user_client_identity",
        sa.Column("id", IDInteger, nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("login_key", sa.String(), nullable=False),
        sa.Column("passwd", sa.String(), nullable=True),
        sa.Column("external_user_id", sa.String(), nullable=True),
        sa.Column("insert_date", IDInteger, nullable=False),
        sa.Column("update_date", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile", "login_key"),
        sa.UniqueConstraint("user_id", "profile"),
    )
    op.create_index(op.f("ix_user_client_identity_user_id"), "user_client_identity", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_client_identity_profile"), "user_client_identity", ["profile"], unique=False)
    op.create_index(op.f("ix_user_client_identity_login_key"), "user_client_identity", ["login_key"], unique=False)
    op.create_index(
        op.f("ix_user_client_identity_external_user_id"),
        "user_client_identity",
        ["external_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_user_client_identity_insert_date"), "user_client_identity", ["insert_date"], unique=False)
    op.create_index(op.f("ix_user_client_identity_update_date"), "user_client_identity", ["update_date"], unique=False)

    op.create_table(
        "random_live_session",
        sa.Column("id", IDInteger, nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("user_id", IDInteger, nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", IDInteger, nullable=False),
        sa.Column("expires_at", IDInteger, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(op.f("ix_random_live_session_token"), "random_live_session", ["token"], unique=True)
    op.create_index(op.f("ix_random_live_session_user_id"), "random_live_session", ["user_id"], unique=False)
    op.create_index(op.f("ix_random_live_session_profile"), "random_live_session", ["profile"], unique=False)
    op.create_index(op.f("ix_random_live_session_created_at"), "random_live_session", ["created_at"], unique=False)
    op.create_index(op.f("ix_random_live_session_expires_at"), "random_live_session", ["expires_at"], unique=False)

    bind = op.get_bind()
    default_profile = npps4_config.get_default_profile().value
    bind.execute(sa.text("UPDATE session SET profile = :profile"), {"profile": default_profile})

    # Preserve all v4.60 accounts.  The old key/passwd pair becomes the login
    # identity for the historical default profile.  The server can later bind
    # the same shared user to the other profile without duplicating progress.
    rows = bind.execute(sa.text('SELECT id, "key", passwd, insert_date, update_date FROM "user" WHERE "key" IS NOT NULL')).fetchall()
    for row in rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO user_client_identity
                    (user_id, profile, login_key, passwd, external_user_id, insert_date, update_date)
                VALUES
                    (:user_id, :profile, :login_key, :passwd, NULL, :insert_date, :update_date)
                """
            ),
            {
                "user_id": row[0],
                "profile": default_profile,
                "login_key": row[1],
                "passwd": row[2],
                "insert_date": row[3],
                "update_date": row[4],
            },
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_random_live_session_expires_at"), table_name="random_live_session")
    op.drop_index(op.f("ix_random_live_session_created_at"), table_name="random_live_session")
    op.drop_index(op.f("ix_random_live_session_profile"), table_name="random_live_session")
    op.drop_index(op.f("ix_random_live_session_user_id"), table_name="random_live_session")
    op.drop_index(op.f("ix_random_live_session_token"), table_name="random_live_session")
    op.drop_table("random_live_session")

    op.drop_index(op.f("ix_user_client_identity_update_date"), table_name="user_client_identity")
    op.drop_index(op.f("ix_user_client_identity_insert_date"), table_name="user_client_identity")
    op.drop_index(op.f("ix_user_client_identity_external_user_id"), table_name="user_client_identity")
    op.drop_index(op.f("ix_user_client_identity_login_key"), table_name="user_client_identity")
    op.drop_index(op.f("ix_user_client_identity_profile"), table_name="user_client_identity")
    op.drop_index(op.f("ix_user_client_identity_user_id"), table_name="user_client_identity")
    op.drop_table("user_client_identity")

    with op.batch_alter_table("session", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_session_profile"))
        batch_op.drop_column("server_rsa_label")
        batch_op.drop_column("profile")
