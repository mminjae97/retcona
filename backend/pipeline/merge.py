"""Result merging and auto-apply (design doc 7.1, 7.3, 7.4).

- merge_and_dedupe: merges the results of the three judgment modules and removes
  duplicate detections of the same underlying error
- Claims not flagged as contradictions are automatically appended to
  character_state_history/location_state_history (7.4). Only claims flagged as
  contradictions are applied after author confirmation.
"""


def merge_and_dedupe(flags_by_module: list[list[dict]]) -> list[dict]:
    # TODO: remove duplicates of the same underlying error, then sort by confidence (2.5)
    raise NotImplementedError


def auto_apply_non_contradicting_claims(novel_id: str, claims: list[dict], flags: list[dict]) -> None:
    # TODO: auto-apply only claims not included in flags to state_history (7.4)
    raise NotImplementedError
