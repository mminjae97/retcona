"""add claims.link_requested_at

Revision ID: f6b2d8a41c93
Revises: e4a7b9c2d6f1
Create Date: 2026-10-06 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6b2d8a41c93'
down_revision = 'e4a7b9c2d6f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('claims', sa.Column('link_requested_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('claims', 'link_requested_at')
