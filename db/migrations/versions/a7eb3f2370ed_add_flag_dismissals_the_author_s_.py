"""add flag_dismissals (the author's dismissals, kept across validation runs)

Revision ID: a7eb3f2370ed
Revises: 46715ce1ca46
Create Date: 2026-09-25 17:16:44.038685

"""
import re
import unicodedata
import uuid

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
    _carry_over_dismissed_flags()


# A frozen copy of pipeline/dismissals.dismissal_key (and the entities.py
# normalization it uses) as of this revision: a migration mustn't depend on
# app code that may change later.
_NOT_WORD = re.compile(r"[\W_]+")


def _normalized(text):
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def _key(subject_id, attribute, evidence, value, reference):
    if subject_id is None or not attribute:
        return None
    if evidence:
        said = "sentence:" + _NOT_WORD.sub("", _normalized(evidence))
    else:
        said = "value:" + _normalized(value or "")
    return subject_id, attribute, said, _normalized(reference or "")


def _carry_over_dismissed_flags():
    # Until now a dismissal lived only on the flag (status 'dismissed'); the
    # next run reads flag_dismissals instead, so those carry over here.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT f.novel_id, c.episode_id, c.subject_id, f.attribute, c.evidence_text, c.attributes, f.reference_text "
            "FROM contradiction_flags f JOIN claims c ON c.id = f.claim_id WHERE f.status = 'dismissed'"
        )
    )
    for novel_id, episode_id, subject_id, attribute, evidence, attributes, reference in rows:
        key = _key(subject_id, attribute, evidence, (attributes or {}).get(attribute), reference)
        if key is None:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO flag_dismissals (id, novel_id, episode_id, subject_id, attribute, said, reference) "
                "VALUES (:id, :novel_id, :episode_id, :subject_id, :attribute, :said, :reference) "
                "ON CONFLICT ON CONSTRAINT uq_flag_dismissals_key DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "novel_id": novel_id,
                "episode_id": episode_id,
                "subject_id": key[0],
                "attribute": key[1],
                "said": key[2],
                "reference": key[3],
            },
        )


def downgrade() -> None:
    op.drop_index(op.f('ix_flag_dismissals_novel_id'), table_name='flag_dismissals')
    op.drop_table('flag_dismissals')
