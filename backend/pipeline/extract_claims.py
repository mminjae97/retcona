"""Extract verification-target claims from the manuscript (design doc 7.1, first step).

Input: novel_id, episode_id, manuscript text
Output: list of Claims (claim_type: appearance | behavior (OOC) | location | spacetime)

Later, entity matching (7.4) compares the character/location names appearing in
the claims against existing characters/locations to decide whether to
auto-register new entities.
"""


def extract_claims(novel_id: str, episode_id: str, manuscript: str) -> list[dict]:
    # TODO: implement LLM-based claim extraction
    raise NotImplementedError
