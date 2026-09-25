"""allow contradiction_flags.confidence to be null (setting changed since it was judged)

Revision ID: 46715ce1ca46
Revises: 8d0813edb934
Create Date: 2026-09-25 10:24:03.488706

"""
from alembic import op
import sqlalchemy as sa


revision = '46715ce1ca46'
down_revision = '8d0813edb934'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('contradiction_flags', 'confidence',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=True)


def downgrade() -> None:
    # Flags waiting to be judged again have no confidence; 0 keeps them last.
    op.execute("UPDATE contradiction_flags SET confidence = 0 WHERE confidence IS NULL")
    op.alter_column('contradiction_flags', 'confidence',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=False)
