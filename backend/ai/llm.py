"""LLM wrapper (design doc chapter 5, 7.2).

Used for claim extraction (the extraction model) and for OOC behavior
judgment and the final verification of ambiguous contradictions (the judgment
model). The actual provider (external/self_hosted/mock) and the two models are
handled by infra.llm_client.
"""

import json

from infra.llm_client import get_llm_client
from models.character import FIXED_ATTR_KEYS, MUTABLE_ATTR_KEYS
from models.location import GEO_ATTR_KEYS

# The manuscript and the known entities go inside these tags. The mock client
# (infra/mock_llm.py) reads them back out of the prompt, the way a model would.
MANUSCRIPT_TAG = "manuscript"
KNOWN_ENTITIES_TAG = "known_entities"

_EXTRACTION_INSTRUCTIONS = f"""\
You extract checkable claims from one episode of a serialized web novel, so
that later steps can compare them against the story's established settings.

A claim is one statement the episode makes about a named character or a named
place, of one of these types:
- appearance: how a character looks (eyes, hair, height, scars, age, outfit, ...)
- behavior: something a character does or says that reflects their personality
- location: what a place is like, or a character being at / moving to a place
- spacetime: when something happens, how much time passes, how long a trip takes

Rules:
- Only named characters and places. Skip pronouns and unnamed people.
- The known characters and locations are listed in <{KNOWN_ENTITIES_TAG}>. Each
  character has a "ref", a "name" and the other names the author has listed
  for it ("aliases"). For a claim about a listed character, set "subject_ref"
  to its ref and "subject" to its "name" — also when the episode calls it by
  an alias or another nickname, title or shortened name. Two characters can
  share a name: tell them apart by the context and their aliases. For a
  character that isn't listed, and for places, leave "subject_ref" out; for a
  listed place, use its listed name as "subject".
- "evidence" is the sentence the claim comes from, copied verbatim.
- "text" restates the claim in one short sentence, in the manuscript's language,
  naming the subject by its "subject" name (never a pronoun or a nickname).
- "attributes" says the claim in setting-card keys, when it maps onto one:
  characters: {", ".join(FIXED_ATTR_KEYS + MUTABLE_ATTR_KEYS)}
  locations: {", ".join(GEO_ATTR_KEYS)}
  Values are short phrases in the manuscript's language. Omit keys that don't apply.

Answer with a single JSON object and nothing else:
{{"claims": [{{"claim_type": "appearance" | "behavior" | "location" | "spacetime",
  "subject_kind": "character" | "location", "subject": "...",
  "subject_ref": "..." (listed characters only), "text": "...",
  "evidence": "...", "attributes": {{"<key>": "..."}}}}]}}
"""


def build_extraction_prompt(manuscript: str, known_characters: list[dict], known_locations: list[str]) -> str:
    # known_characters: {"ref", "name", "aliases"} each
    known = json.dumps({"characters": known_characters, "locations": known_locations}, ensure_ascii=False)
    return (
        f"{_EXTRACTION_INSTRUCTIONS}\n"
        f"<{KNOWN_ENTITIES_TAG}>\n{known}\n</{KNOWN_ENTITIES_TAG}>\n\n"
        f"<{MANUSCRIPT_TAG}>\n{manuscript}\n</{MANUSCRIPT_TAG}>\n"
    )


def extract_claims(manuscript: str, known_characters: list[dict], known_locations: list[str]) -> str:
    """The raw model response to the claim-extraction prompt; parsing and
    checking it is pipeline/extract_claims.py's job."""
    return get_llm_client("extraction").complete(build_extraction_prompt(manuscript, known_characters, known_locations))


def judge_ooc(character_profile: dict, manuscript_excerpt: str) -> dict:
    prompt = f"Personality/speech profile: {character_profile}\n\nDetermine whether the following narration conflicts with the profile above:\n{manuscript_excerpt}"
    result = get_llm_client("judgment").complete(prompt)
    # TODO: parse the LLM response
    return {"raw": result}
