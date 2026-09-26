"""key flag_dismissals by card id again (characters can share a name)

Revision ID: b3c1d9e5f7a2
Revises: 59ef8449f085
Create Date: 2026-09-26 10:00:00.000000

"""
import unicodedata

from alembic import op
import sqlalchemy as sa


revision = 'b3c1d9e5f7a2'
down_revision = '59ef8449f085'
branch_labels = None
depends_on = None


# A frozen copy of pipeline/entities.normalize_name as of this revision.
def _normalized(text):
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def upgrade() -> None:
    op.add_column('flag_dismissals', sa.Column('subject_id', sa.UUID(), nullable=True))
    bind = op.get_bind()
    # Back to the card of that kind and name in the novel (the oldest, as
    # entity matching picked until now); a name with no card left is dropped.
    cards = {}
    for table, kind in (("characters", "character"), ("locations", "location")):
        for card_id, novel_id, name in bind.execute(
            sa.text(f"SELECT id, novel_id, name FROM {table} ORDER BY created_at, id")
        ):
            cards.setdefault((novel_id, f"{kind}:{_normalized(name)}"), card_id)
    for dismissal_id, novel_id, subject in bind.execute(sa.text("SELECT id, novel_id, subject FROM flag_dismissals")).all():
        card_id = cards.get((novel_id, subject))
        if card_id is not None:
            bind.execute(
                sa.text("UPDATE flag_dismissals SET subject_id = :card WHERE id = :id"), {"card": card_id, "id": dismissal_id}
            )
    bind.execute(sa.text("DELETE FROM flag_dismissals WHERE subject_id IS NULL"))
    op.alter_column('flag_dismissals', 'subject_id', nullable=False)
    op.drop_constraint('uq_flag_dismissals_key', 'flag_dismissals', type_='unique')
    op.drop_column('flag_dismissals', 'subject')
    op.create_unique_constraint(
        'uq_flag_dismissals_key', 'flag_dismissals', ['episode_id', 'subject_id', 'attribute', 'said', 'reference']
    )


def downgrade() -> None:
    op.add_column('flag_dismissals', sa.Column('subject', sa.Text(), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT d.id, 'character', c.name FROM flag_dismissals d JOIN characters c ON c.id = d.subject_id "
            "UNION ALL "
            "SELECT d.id, 'location', l.name FROM flag_dismissals d JOIN locations l ON l.id = d.subject_id"
        )
    ).all()
    for dismissal_id, kind, name in rows:
        bind.execute(
            sa.text("UPDATE flag_dismissals SET subject = :subject WHERE id = :id"),
            {"subject": f"{kind}:{_normalized(name)}", "id": dismissal_id},
        )
    bind.execute(sa.text("DELETE FROM flag_dismissals WHERE subject IS NULL"))
    # Two cards with one name make one key: keep one row of each.
    bind.execute(
        sa.text(
            "DELETE FROM flag_dismissals d USING flag_dismissals e "
            "WHERE d.episode_id = e.episode_id AND d.subject = e.subject AND d.attribute = e.attribute "
            "AND d.said = e.said AND d.reference = e.reference AND d.id > e.id"
        )
    )
    op.alter_column('flag_dismissals', 'subject', nullable=False)
    op.drop_constraint('uq_flag_dismissals_key', 'flag_dismissals', type_='unique')
    op.drop_column('flag_dismissals', 'subject_id')
    op.create_unique_constraint(
        'uq_flag_dismissals_key', 'flag_dismissals', ['episode_id', 'subject', 'attribute', 'said', 'reference']
    )
