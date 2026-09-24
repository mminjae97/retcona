"""add attr_sources on cards and attribute/reference_text on contradiction_flags

Revision ID: 8d0813edb934
Revises: bd0b2f811d66
Create Date: 2026-09-24 09:59:28.517402

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '8d0813edb934'
down_revision = 'bd0b2f811d66'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('attr_sources', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('contradiction_flags', sa.Column('attribute', sa.String(), nullable=True))
    op.add_column('contradiction_flags', sa.Column('reference_text', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('attr_sources', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))


def downgrade() -> None:
    op.drop_column('locations', 'attr_sources')
    op.drop_column('contradiction_flags', 'reference_text')
    op.drop_column('contradiction_flags', 'attribute')
    op.drop_column('characters', 'attr_sources')
