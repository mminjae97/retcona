"""add claims.candidates, claims.link_status and claim_link_choices

Revision ID: e4a7b9c2d6f1
Revises: c8f1a3d95e27
Create Date: 2026-10-06 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'e4a7b9c2d6f1'
down_revision = 'c8f1a3d95e27'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('claims', sa.Column('candidates', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('claims', sa.Column('link_status', sa.String(), nullable=True))
    op.create_table(
        'claim_link_choices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('episode_id', sa.UUID(), nullable=False),
        sa.Column('said', sa.Text(), nullable=False),
        sa.Column('subject_id', sa.UUID(), nullable=True),
        sa.Column('novel_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id']),
        sa.ForeignKeyConstraint(['novel_id'], ['novels.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('episode_id', 'said', name='uq_claim_link_choices_key'),
    )
    op.create_index(op.f('ix_claim_link_choices_novel_id'), 'claim_link_choices', ['novel_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_claim_link_choices_novel_id'), table_name='claim_link_choices')
    op.drop_table('claim_link_choices')
    op.drop_column('claims', 'link_status')
    op.drop_column('claims', 'candidates')
