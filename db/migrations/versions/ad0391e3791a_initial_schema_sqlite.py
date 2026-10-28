"""initial schema (SQLite)

Revision ID: ad0391e3791a
Revises:
Create Date: 2026-10-28 11:34:56.333670

The whole schema, for SQLite (design doc 10.1), in place of the PostgreSQL
migrations before it: the app's data starts afresh in its data folder. Every
foreign key cascades (a novel deleted for good takes everything under it,
pipeline/empty_trash.py), and every foreign key column is indexed, so a
cascade doesn't read a whole table per row.
Timestamps (UtcDateTime in the models) are text in UTC.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ad0391e3791a'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=True),
    sa.Column('payload', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index('ix_jobs_status_created', ['status', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_jobs_target_id'), ['target_id'], unique=False)

    op.create_table('novels',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('characters',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('aliases', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('gender', sa.String(), server_default='unspecified', nullable=False),
    sa.Column('pronoun', sa.String(), nullable=True),
    sa.Column('appears_after_death', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('fixed_attrs', sa.JSON(), nullable=False),
    sa.Column('mutable_attrs', sa.JSON(), nullable=False),
    sa.Column('personality', sa.JSON(), nullable=False),
    sa.Column('attr_sources', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('characters', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_characters_novel_id'), ['novel_id'], unique=False)

    op.create_table('episodes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('novel_id', 'episode_index', name='uq_episodes_novel_id_episode_index')
    )
    with op.batch_alter_table('episodes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_episodes_novel_id'), ['novel_id'], unique=False)

    op.create_table('locations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('geo_attrs', sa.JSON(), nullable=False),
    sa.Column('attr_sources', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_locations_novel_id'), ['novel_id'], unique=False)

    op.create_table('relations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('from_entity_id', sa.Uuid(), nullable=False),
    sa.Column('to_entity_id', sa.Uuid(), nullable=False),
    sa.Column('entity_kind', sa.String(), nullable=False),
    sa.Column('relation_type', sa.String(), nullable=False),
    sa.Column('direction', sa.String(), nullable=True),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('relations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_relations_novel_id'), ['novel_id'], unique=False)

    op.create_table('story_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_index', sa.Integer(), nullable=False),
    sa.Column('story_timestamp', sa.DateTime(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('story_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_story_events_novel_id'), ['novel_id'], unique=False)

    op.create_table('world_settings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('world_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_world_settings_novel_id'), ['novel_id'], unique=False)

    op.create_table('character_state_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('character_id', sa.Uuid(), nullable=False),
    sa.Column('episode_index', sa.Integer(), nullable=False),
    sa.Column('story_timestamp', sa.DateTime(), nullable=True),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('character_state_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_character_state_history_character_id'), ['character_id'], unique=False)
        batch_op.create_index('ix_character_state_history_novel_char_episode', ['novel_id', 'character_id', 'episode_index'], unique=False)
        batch_op.create_index('ix_character_state_history_novel_char_story_ts', ['novel_id', 'character_id', 'story_timestamp'], unique=False)
        batch_op.create_index(batch_op.f('ix_character_state_history_novel_id'), ['novel_id'], unique=False)

    op.create_table('claim_link_choices',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('said', sa.Text(), nullable=False),
    sa.Column('subject_id', sa.Uuid(), nullable=True),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('episode_id', 'said', name='uq_claim_link_choices_key')
    )
    with op.batch_alter_table('claim_link_choices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_claim_link_choices_episode_id'), ['episode_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_claim_link_choices_novel_id'), ['novel_id'], unique=False)

    op.create_table('claims',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('claim_type', sa.String(), nullable=False),
    sa.Column('subject_kind', sa.String(), nullable=True),
    sa.Column('subject_id', sa.Uuid(), nullable=True),
    sa.Column('subject_name', sa.String(), nullable=True),
    sa.Column('evidence_text', sa.Text(), nullable=True),
    sa.Column('attributes', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('candidates', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('link_status', sa.String(), nullable=True),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_claims_episode_id'), ['episode_id'], unique=False)
        batch_op.create_index('ix_claims_novel_episode', ['novel_id', 'episode_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_claims_novel_id'), ['novel_id'], unique=False)

    op.create_table('event_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('from_event_id', sa.Uuid(), nullable=False),
    sa.Column('to_event_id', sa.Uuid(), nullable=False),
    sa.Column('link_type', sa.String(), nullable=False),
    sa.Column('branch_reason', sa.Text(), nullable=True),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['from_event_id'], ['story_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_event_id'], ['story_events.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('event_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_event_links_from_event_id'), ['from_event_id'], unique=False)
        batch_op.create_index('ix_event_links_novel_from_event', ['novel_id', 'from_event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_links_novel_id'), ['novel_id'], unique=False)
        batch_op.create_index('ix_event_links_novel_to_event', ['novel_id', 'to_event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_links_to_event_id'), ['to_event_id'], unique=False)

    op.create_table('event_locations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['story_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('event_locations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_event_locations_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_locations_location_id'), ['location_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_locations_novel_id'), ['novel_id'], unique=False)

    op.create_table('event_participants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('character_id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['event_id'], ['story_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('event_participants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_event_participants_character_id'), ['character_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_participants_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_participants_novel_id'), ['novel_id'], unique=False)

    op.create_table('flag_dismissals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('subject_id', sa.Uuid(), nullable=False),
    sa.Column('attribute', sa.String(), nullable=False),
    sa.Column('said', sa.Text(), nullable=False),
    sa.Column('reference', sa.Text(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('episode_id', 'subject_id', 'attribute', 'said', 'reference', name='uq_flag_dismissals_key')
    )
    with op.batch_alter_table('flag_dismissals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_flag_dismissals_episode_id'), ['episode_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_flag_dismissals_novel_id'), ['novel_id'], unique=False)

    op.create_table('location_state_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('episode_index', sa.Integer(), nullable=False),
    sa.Column('story_timestamp', sa.DateTime(), nullable=True),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('location_state_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_location_state_history_location_id'), ['location_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_location_state_history_novel_id'), ['novel_id'], unique=False)
        batch_op.create_index('ix_location_state_history_novel_loc_episode', ['novel_id', 'location_id', 'episode_index'], unique=False)
        batch_op.create_index('ix_location_state_history_novel_loc_story_ts', ['novel_id', 'location_id', 'story_timestamp'], unique=False)

    op.create_table('validation_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('summary', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('content_updated_at', sa.DateTime(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('validation_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_validation_runs_episode_id'), ['episode_id'], unique=False)
        batch_op.create_index('ix_validation_runs_novel_episode_created', ['novel_id', 'episode_id', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_validation_runs_novel_id'), ['novel_id'], unique=False)

    op.create_table('contradiction_flags',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('claim_id', sa.Uuid(), nullable=False),
    sa.Column('error_type', sa.String(), nullable=False),
    sa.Column('attribute', sa.String(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('evidence_text', sa.Text(), nullable=False),
    sa.Column('reference_text', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contradiction_flags', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contradiction_flags_claim_id'), ['claim_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_contradiction_flags_novel_id'), ['novel_id'], unique=False)

    op.create_table('flag_revalidations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('flag_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('outcome', sa.String(), nullable=True),
    sa.Column('setting', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text("(strftime('%Y-%m-%d %H:%M:%f000', 'now'))"), nullable=False),
    sa.ForeignKeyConstraint(['flag_id'], ['contradiction_flags.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('flag_revalidations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_flag_revalidations_flag_id'), ['flag_id'], unique=False)
        batch_op.create_index('ix_flag_revalidations_novel_flag_created', ['novel_id', 'flag_id', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_flag_revalidations_novel_id'), ['novel_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('flag_revalidations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_flag_revalidations_novel_id'))
        batch_op.drop_index('ix_flag_revalidations_novel_flag_created')
        batch_op.drop_index(batch_op.f('ix_flag_revalidations_flag_id'))

    op.drop_table('flag_revalidations')
    with op.batch_alter_table('contradiction_flags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contradiction_flags_novel_id'))
        batch_op.drop_index(batch_op.f('ix_contradiction_flags_claim_id'))

    op.drop_table('contradiction_flags')
    with op.batch_alter_table('validation_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_validation_runs_novel_id'))
        batch_op.drop_index('ix_validation_runs_novel_episode_created')
        batch_op.drop_index(batch_op.f('ix_validation_runs_episode_id'))

    op.drop_table('validation_runs')
    with op.batch_alter_table('location_state_history', schema=None) as batch_op:
        batch_op.drop_index('ix_location_state_history_novel_loc_story_ts')
        batch_op.drop_index('ix_location_state_history_novel_loc_episode')
        batch_op.drop_index(batch_op.f('ix_location_state_history_novel_id'))
        batch_op.drop_index(batch_op.f('ix_location_state_history_location_id'))

    op.drop_table('location_state_history')
    with op.batch_alter_table('flag_dismissals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_flag_dismissals_novel_id'))
        batch_op.drop_index(batch_op.f('ix_flag_dismissals_episode_id'))

    op.drop_table('flag_dismissals')
    with op.batch_alter_table('event_participants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_event_participants_novel_id'))
        batch_op.drop_index(batch_op.f('ix_event_participants_event_id'))
        batch_op.drop_index(batch_op.f('ix_event_participants_character_id'))

    op.drop_table('event_participants')
    with op.batch_alter_table('event_locations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_event_locations_novel_id'))
        batch_op.drop_index(batch_op.f('ix_event_locations_location_id'))
        batch_op.drop_index(batch_op.f('ix_event_locations_event_id'))

    op.drop_table('event_locations')
    with op.batch_alter_table('event_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_event_links_to_event_id'))
        batch_op.drop_index('ix_event_links_novel_to_event')
        batch_op.drop_index(batch_op.f('ix_event_links_novel_id'))
        batch_op.drop_index('ix_event_links_novel_from_event')
        batch_op.drop_index(batch_op.f('ix_event_links_from_event_id'))

    op.drop_table('event_links')
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_claims_novel_id'))
        batch_op.drop_index('ix_claims_novel_episode')
        batch_op.drop_index(batch_op.f('ix_claims_episode_id'))

    op.drop_table('claims')
    with op.batch_alter_table('claim_link_choices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_claim_link_choices_novel_id'))
        batch_op.drop_index(batch_op.f('ix_claim_link_choices_episode_id'))

    op.drop_table('claim_link_choices')
    with op.batch_alter_table('character_state_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_character_state_history_novel_id'))
        batch_op.drop_index('ix_character_state_history_novel_char_story_ts')
        batch_op.drop_index('ix_character_state_history_novel_char_episode')
        batch_op.drop_index(batch_op.f('ix_character_state_history_character_id'))

    op.drop_table('character_state_history')
    with op.batch_alter_table('world_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_world_settings_novel_id'))

    op.drop_table('world_settings')
    with op.batch_alter_table('story_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_story_events_novel_id'))

    op.drop_table('story_events')
    with op.batch_alter_table('relations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_relations_novel_id'))

    op.drop_table('relations')
    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_locations_novel_id'))

    op.drop_table('locations')
    with op.batch_alter_table('episodes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_episodes_novel_id'))

    op.drop_table('episodes')
    with op.batch_alter_table('characters', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_characters_novel_id'))

    op.drop_table('characters')
    op.drop_table('novels')
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_jobs_target_id'))
        batch_op.drop_index('ix_jobs_status_created')

    op.drop_table('jobs')
