"""add users.token_version

Revision ID: e7b2d4f1a8c3
Revises: cd25aa9ab9fa
Create Date: 2026-09-21 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e7b2d4f1a8c3'
down_revision = 'cd25aa9ab9fa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'token_version')
