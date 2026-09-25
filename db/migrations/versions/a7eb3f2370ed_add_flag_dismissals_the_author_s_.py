"""add flag_dismissals (the author's dismissals, kept across validation runs)

Revision ID: a7eb3f2370ed
Revises: 46715ce1ca46
Create Date: 2026-09-25 17:16:44.038685

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7eb3f2370ed'
down_revision = '46715ce1ca46'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('flag_dismissals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('episode_id', sa.UUID(), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column('attribute', sa.String(), nullable=False),
    sa.Column('said', sa.Text(), nullable=False),
    sa.Column('reference', sa.Text(), nullable=False),
    sa.Column('novel_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('episode_id', 'subject_id', 'attribute', 'said', 'reference', name='uq_flag_dismissals_key')
    )
    op.create_index(op.f('ix_flag_dismissals_novel_id'), 'flag_dismissals', ['novel_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_flag_dismissals_novel_id'), table_name='flag_dismissals')
    op.drop_table('flag_dismissals')
