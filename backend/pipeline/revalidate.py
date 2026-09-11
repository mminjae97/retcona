"""Revalidation after adding missing settings (design doc 7.5).

Instead of rerunning the whole pipeline, only the judgment module that raised
the flag is rerun with a fresh context bundle (saves cost). Revalidation is
also processed asynchronously through the job queue (10.2).

If resolved, status transitions to resolved_by_revalidation, and evidence of
which setting was added to resolve it is recorded (useful for reducing false
positives later).
"""


def revalidate_flag(novel_id: str, flag_id: str) -> dict:
    # TODO:
    #   1. Determine error_type (appearance/location/spacetime) from flag_id and call only the matching judge function
    #   2. Contradiction resolved -> status=resolved_by_revalidation, record the resolution evidence
    #   3. Still contradicting -> keep status as open, update evidence_text
    raise NotImplementedError
