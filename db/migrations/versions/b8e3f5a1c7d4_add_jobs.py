"""add jobs (the local job queue)

The queue moves from Redis into the database (design doc 10.2): a job is
queued in the same transaction as the row it works on, and one left running
when the app closed runs again at the next start. Runs, revalidations and
picks still waiting from the Redis queue have no job here; the API fails them
as abandoned when it next reads them, so they can be run again.

claims.link_requested_at goes: a pick is put back when no job is left for it,
not some time after it was made.

Revision ID: b8e3f5a1c7d4
Revises: c4d7e1a9f2b6
Create Date: 2026-10-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'b8e3f5a1c7d4'
down_revision = 'c4d7e1a9f2b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_status_created', 'jobs', ['status', 'created_at'], unique=False)
    op.create_index(op.f('ix_jobs_target_id'), 'jobs', ['target_id'], unique=False)
    op.drop_column('claims', 'link_requested_at')


def downgrade() -> None:
    # Jobs still queued are dropped with the table: the code before this
    # revision reads the Redis queue, and fails what they were for as abandoned
    # 15 minutes after it was requested. Picks still waiting count from now,
    # as their time was dropped with the column.
    op.add_column('claims', sa.Column('link_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE claims SET link_requested_at = now() WHERE link_status IN ('queued', 'judging')")
    op.drop_index(op.f('ix_jobs_target_id'), table_name='jobs')
    op.drop_index('ix_jobs_status_created', table_name='jobs')
    op.drop_table('jobs')
