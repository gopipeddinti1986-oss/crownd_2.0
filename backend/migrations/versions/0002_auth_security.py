"""Add verified email state, revocable sessions, and one-use account tokens.

This revision accommodates the existing dynamic 0001 migration: a database created
with newer ORM metadata may already contain these additions, while an existing DB
will be upgraded additively.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision="0002_auth_security"
down_revision="0001_initial"
branch_labels=None
depends_on=None

def upgrade():
    inspector=inspect(op.get_bind())
    user_columns={col["name"] for col in inspector.get_columns("users")}
    if "email_verified" not in user_columns:
        op.add_column("users",sa.Column("email_verified",sa.Boolean(),nullable=False,server_default=sa.true()))
    tables=set(inspect(op.get_bind()).get_table_names())
    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id",sa.String(length=40),primary_key=True),
            sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
            sa.Column("refresh_token_hash",sa.String(length=64),nullable=False,unique=True),
            sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
            sa.Column("revoked_at",sa.DateTime(timezone=True),nullable=True),
            sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
            sa.Column("last_used_at",sa.DateTime(timezone=True),nullable=False),
        )
    indexes={index["name"] for index in inspect(op.get_bind()).get_indexes("auth_sessions")}
    for name,column in (("ix_auth_sessions_user_id","user_id"),("ix_auth_sessions_refresh_token_hash","refresh_token_hash"),("ix_auth_sessions_expires_at","expires_at")):
        if name not in indexes: op.create_index(name,"auth_sessions",[column],unique=column=="refresh_token_hash")
    tables=set(inspect(op.get_bind()).get_table_names())
    if "auth_action_tokens" not in tables:
        op.create_table(
            "auth_action_tokens",
            sa.Column("id",sa.Integer(),primary_key=True),
            sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
            sa.Column("purpose",sa.String(length=24),nullable=False),
            sa.Column("token_hash",sa.String(length=64),nullable=False,unique=True),
            sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
            sa.Column("consumed_at",sa.DateTime(timezone=True),nullable=True),
            sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        )
    indexes={index["name"] for index in inspect(op.get_bind()).get_indexes("auth_action_tokens")}
    for name,column,unique in (("ix_auth_action_tokens_user_id","user_id",False),("ix_auth_action_tokens_purpose","purpose",False),("ix_auth_action_tokens_token_hash","token_hash",True),("ix_auth_action_tokens_expires_at","expires_at",False)):
        if name not in indexes: op.create_index(name,"auth_action_tokens",[column],unique=unique)

def downgrade():
    op.drop_table("auth_action_tokens")
    op.drop_table("auth_sessions")
    if "email_verified" in {col["name"] for col in inspect(op.get_bind()).get_columns("users")}:
        op.drop_column("users","email_verified")
