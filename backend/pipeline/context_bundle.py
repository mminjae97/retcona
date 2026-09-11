"""Shared context lookup (design doc 7.1, 7.3).

Instead of each of the three judgment modules (appearance/behavior, location,
spacetime) querying the DB separately, they share the context bundle this
function assembles once (avoids context silos, 7.3).

novel_id is a required argument, passed through unchanged to every underlying query (10.1).
"""


def get_context_bundle(novel_id: str, claims: list[dict]) -> dict:
    # TODO: narrow down characters, locations, world_settings, relations,
    #       character_state_history, location_state_history, etc. to only the
    #       relevant items via pgvector similarity search (novel_id filter
    #       required, 10.1) + reranker, and return them
    raise NotImplementedError
