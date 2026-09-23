"""add signup email verification (email_verifications, users.email_verified_at)

Revision ID: b5d8e2a1c7f4
Revises: e7b2d4f1a8c3
Create Date: 2026-09-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b5d8e2a1c7f4'
down_revision = 'e7b2d4f1a8c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'email_verifications',
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('code_hash', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sends_in_window', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('email'),
    )
    # Null for accounts created before this: they never verified their email.
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'email_verified_at')
    op.drop_table('email_verifications')
