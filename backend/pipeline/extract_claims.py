"""Extract verification-target claims from the manuscript (design doc 7.1, first step).

Input: novel_id, manuscript text, the novel's known character/location names
  (characters with their aliases)
Output: list of ExtractedClaims (claim_type: appearance | behavior (OOC) | location | spacetime)

The model is asked to name each claim's subject by its listed name when the
manuscript refers to a known character or location by another name, so entity
matching (pipeline/entities.py, 7.4) can match on names alone. A character the
model still names by one of its listed aliases is renamed after it
(pipeline/entities.py resolve_aliases).

What the model returns is checked here, item by item: a malformed claim is
dropped (and counted in the log) rather than failing the whole episode, but a
response that isn't the expected JSON at all is an ExtractionError.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from ai import llm
from models.character import FIXED_ATTR_KEYS, MUTABLE_ATTR_KEYS
from models.location import GEO_ATTR_KEYS

logger = logging.getLogger(__name__)

# The same limits the settings screen puts on a card (api/settings.py), so a
# card created from a claim fits what that screen can save back.
NAME_MAX_LENGTH = 100
ATTR_MAX_LENGTH = 500
_TEXT_MAX_LENGTH = 2000

_ATTR_KEYS = {
    "character": set(FIXED_ATTR_KEYS + MUTABLE_ATTR_KEYS),
    "location": set(GEO_ATTR_KEYS),
}


class ExtractionError(Exception):
    """The model's response couldn't be read as an extraction result."""


class ExtractedClaim(BaseModel):
    claim_type: Literal["appearance", "behavior", "location", "spacetime"]
    subject_kind: Literal["character", "location"]
    subject: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    text: str = Field(min_length=1)
    evidence: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("subject", "text", "evidence", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("text", "evidence")
    @classmethod
    def _truncate(cls, value: str | None) -> str | None:
        # A blank evidence reads as none (text can't be blank: min_length).
        return value[:_TEXT_MAX_LENGTH] if value else None

    @field_validator("attributes", mode="before")
    @classmethod
    def _attributes_as_text(cls, value: object) -> object:
        # Values as text (a model may give an age as 17). Something that isn't
        # an object at all loses the attributes, not the claim.
        if not isinstance(value, dict):
            return {}
        return {str(key): str(item).strip()[:ATTR_MAX_LENGTH] for key, item in value.items() if item is not None}

    @model_validator(mode="after")
    def _card_keys_only(self) -> "ExtractedClaim":
        # Only the keys a card of this kind has (a location has no eye color), non-empty.
        allowed = _ATTR_KEYS[self.subject_kind]
        self.attributes = {key: value for key, value in self.attributes.items() if key in allowed and value}
        return self


@dataclass
class Extraction:
    claims: list[ExtractedClaim] = field(default_factory=list)
    dropped: int = 0


def _json_object(raw: str) -> dict:
    # Models sometimes wrap the object in a code fence or a sentence; take the
    # outermost {...}.
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end < start:
        raise ExtractionError("no JSON object in the response")
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ExtractionError("the response is not a JSON object")
    return value


def parse_extraction(raw: str) -> Extraction:
    items = _json_object(raw).get("claims", [])
    if not isinstance(items, list):
        raise ExtractionError('"claims" is not a list')
    extraction = Extraction()
    for item in items:
        try:
            extraction.claims.append(ExtractedClaim.model_validate(item))
        except ValidationError:
            extraction.dropped += 1
    return extraction


def extract_claims(
    novel_id: uuid.UUID, manuscript: str, known_characters: dict[str, list[str]], known_locations: list[str]
) -> Extraction:
    extraction = parse_extraction(llm.extract_claims(manuscript, known_characters, known_locations))
    if extraction.dropped:
        logger.warning(
            "Novel %s: dropped %d malformed claim(s) from the extraction, kept %d",
            novel_id,
            extraction.dropped,
            len(extraction.claims),
        )
    return extraction
