"""add characters.appears_after_death

Revision ID: a9c4e1f7b3d2
Revises: f6b2d8a41c93
Create Date: 2026-10-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a9c4e1f7b3d2'
down_revision = 'f6b2d8a41c93'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'characters', sa.Column('appears_after_death', sa.Boolean(), server_default=sa.false(), nullable=False)
    )


def downgrade() -> None:
    op.drop_column('characters', 'appears_after_death')
