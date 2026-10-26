"""remove accounts (users, email_verifications, novels.user_id)

The desktop app has no accounts (design doc 4.1): novels are the top level.
Every user's novels stay, as the one author's, except those of an account put up
for deletion (3.5 of the web service): they are deleted for good, with every row
under their novel_id, as the deletion promised (the purge job that would have
done it goes with the accounts).

Revision ID: c4d7e1a9f2b6
Revises: a9c4e1f7b3d2
Create Date: 2026-10-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d7e1a9f2b6'
down_revision = 'a9c4e1f7b3d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    doomed = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT n.id FROM novels n JOIN users u ON u.id = n.user_id "
                "WHERE u.deletion_requested_at IS NOT NULL"
            )
        )
    ]
    if doomed:
        tables = sa.MetaData()
        tables.reflect(bind)
        # Children first (sorted_tables lists parents before children), as the
        # purge job did: every table but users and novels carries novel_id.
        for table in reversed(tables.sorted_tables):
            if "novel_id" in table.c:
                bind.execute(table.delete().where(table.c.novel_id.in_(doomed)))
        novels = tables.tables["novels"]
        bind.execute(novels.delete().where(novels.c.id.in_(doomed)))
    op.drop_constraint('novels_user_id_fkey', 'novels', type_='foreignkey')
    op.drop_column('novels', 'user_id')
    op.drop_table('email_verifications')
    op.drop_table('users')


def downgrade() -> None:
    # The schema only: the accounts themselves are gone and can't be brought
    # back, so novels.user_id returns empty (nullable). The code before this
    # revision shows a novel only to its owner: to use the novels with it, sign
    # up again, then give them to that account by hand:
    #   UPDATE novels SET user_id = (SELECT id FROM users WHERE email = '<your email>');
    #   ALTER TABLE novels ALTER COLUMN user_id SET NOT NULL;
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('nickname', sa.String(length=20), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('provider_id', sa.String(), nullable=True),
        sa.Column('password_hash', sa.String(), nullable=True),
        sa.Column('deletion_requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('token_version', sa.Integer(), server_default='0', nullable=False),
        sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
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
    op.add_column('novels', sa.Column('user_id', sa.UUID(), nullable=True))
    op.create_foreign_key('novels_user_id_fkey', 'novels', 'users', ['user_id'], ['id'])
