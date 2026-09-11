"""The three judgment modules (design doc 7.2).

They share the same interface (claims + context_bundle in -> flags out) so
they can run in parallel and be swapped out easily (6.2).

| Module | Main input fields | Judgment method |
|---|---|---|
| Appearance/behavior violation | fixed_attrs, latest_mutable_state, personality, world_settings | Appearance: NLI / Behavior (OOC): LLM |
| Location error | fixed_attrs (terrain), relations (distance) | NLI + rule-based distance calculation |
| Spacetime contradiction | last_known_position, state_history, relations | Rule-based time/distance verification + LLM assist |
"""


def judge_appearance_and_behavior(claims: list[dict], context_bundle: dict) -> list[dict]:
    # TODO: NLI for appearance, LLM + personality/speech profile-based inference for behavior (OOC)
    raise NotImplementedError


def judge_location(claims: list[dict], context_bundle: dict) -> list[dict]:
    # TODO: NLI + rule-based distance calculation
    raise NotImplementedError


def judge_timeline(claims: list[dict], context_bundle: dict) -> list[dict]:
    # TODO: rule-based time/distance verification + LLM assist
    raise NotImplementedError
