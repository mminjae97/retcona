"""add characters.gender and characters.pronoun

Revision ID: c8f1a3d95e27
Revises: d5ee3ddc62cf
Create Date: 2026-10-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c8f1a3d95e27'
down_revision = 'd5ee3ddc62cf'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('gender', sa.String(), server_default='unspecified', nullable=False))
    op.add_column('characters', sa.Column('pronoun', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('characters', 'pronoun')
    op.drop_column('characters', 'gender')
