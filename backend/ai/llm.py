"""LLM wrapper (design doc chapter 5, 7.2).

Used for OOC behavior judgment, final verification of ambiguous contradictions,
and claim extraction. The actual provider (external/self_hosted) is handled by
infra.llm_client.
"""

from infra.llm_client import get_llm_client


def judge_ooc(character_profile: dict, manuscript_excerpt: str) -> dict:
    prompt = f"Personality/speech profile: {character_profile}\n\nDetermine whether the following narration conflicts with the profile above:\n{manuscript_excerpt}"
    result = get_llm_client().complete(prompt)
    # TODO: parse the LLM response
    return {"raw": result}
