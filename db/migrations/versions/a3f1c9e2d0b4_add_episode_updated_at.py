"""add episode updated_at

Revision ID: a3f1c9e2d0b4
Revises: 961f54d79f2a
Create Date: 2026-09-15 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a3f1c9e2d0b4'
down_revision = '961f54d79f2a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'episodes',
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('episodes', 'updated_at')
