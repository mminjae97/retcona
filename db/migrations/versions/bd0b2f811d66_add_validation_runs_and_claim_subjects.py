"""add validation runs (validation_runs) and claim subjects (claims.subject_*, evidence_text, attributes)

Revision ID: bd0b2f811d66
Revises: b5d8e2a1c7f4
Create Date: 2026-09-23 20:19:45.143068

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'bd0b2f811d66'
down_revision = 'b5d8e2a1c7f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('validation_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('episode_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('content_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('novel_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_validation_runs_novel_episode_created', 'validation_runs', ['novel_id', 'episode_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_validation_runs_novel_id'), 'validation_runs', ['novel_id'], unique=False)
    op.add_column('claims', sa.Column('subject_kind', sa.String(), nullable=True))
    op.add_column('claims', sa.Column('subject_id', sa.UUID(), nullable=True))
    op.add_column('claims', sa.Column('subject_name', sa.String(), nullable=True))
    op.add_column('claims', sa.Column('evidence_text', sa.Text(), nullable=True))
    op.add_column('claims', sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.create_index('ix_claims_novel_episode', 'claims', ['novel_id', 'episode_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_claims_novel_episode', table_name='claims')
    op.drop_column('claims', 'attributes')
    op.drop_column('claims', 'evidence_text')
    op.drop_column('claims', 'subject_name')
    op.drop_column('claims', 'subject_id')
    op.drop_column('claims', 'subject_kind')
    op.drop_index(op.f('ix_validation_runs_novel_id'), table_name='validation_runs')
    op.drop_index('ix_validation_runs_novel_episode_created', table_name='validation_runs')
    op.drop_table('validation_runs')
