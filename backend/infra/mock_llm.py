"""Development stand-in for the LLM (LLM_PROVIDER=mock).

No model and no network: it answers the claim-extraction prompt
(ai/llm.py) from keyword rules over the manuscript in that prompt, in the same
JSON a model would return, so the pipeline (claims, entity matching and
auto-registration, 7.4) can run end to end before a real model is chosen
(chapter 5). What it finds is rough — any Korean word of 2-4 syllables used as
a subject at least twice counts as a character — and it judges nothing. Any
other prompt gets an empty JSON object.
"""

import json
import re

from ai.llm import KNOWN_ENTITIES_TAG, MANUSCRIPT_TAG
from infra.llm_client import LLMClient

_SENTENCE_BREAK = re.compile(r"(?<=[.!?…。])\s+|\n+")
# A 2-4 syllable word followed by a subject/topic particle and then a word break.
_SUBJECT = re.compile(r"(?<![가-힣])([가-힣]{2,4})(?:은|는|이|가)(?![가-힣])")
_PLACE_SUFFIXES = "숲|마을|도시|왕국|제국|성채|왕궁|궁전|신전|사원|항구|호수|평원|협곡|산맥|요새|탑"
_PLACE = re.compile(rf"(?<![가-힣])([가-힣]{{1,6}}\s?(?:{_PLACE_SUFFIXES}))(?:에서|으로|로|에|을|를|은|는|이|가|의)?(?![가-힣])")
# Words that look like names to _SUBJECT but aren't.
_NOT_NAMES = {
    "그녀", "그들", "우리", "자신", "사람", "모두", "누구", "무엇", "이것", "그것", "저것", "여기", "거기",
    "하나", "모습", "얼굴", "목소리", "하늘", "바람", "시간", "순간", "마음", "생각", "소리", "눈빛",
    "눈동자", "머리", "머리카락", "사내", "소녀", "소년", "여자", "남자", "아이", "기사", "병사",
}
_APPEARANCE = {
    "눈동자": "eye_color",
    "머리카락": "hair_color",
    "머리칼": "hair_color",
    "흉터": "scars",
    "키가": "height",
    "옷차림": "outfit",
    "상처": "condition",
}
_AGE = re.compile(r"(?:[0-9]+|[가-힣]{1,4})\s?살")
_TIME_WORDS = ("다음 날", "이튿날", "사흘", "며칠", "일주일", "한 달", "년 후", "새벽", "아침", "저녁", "밤")
_QUOTES = ('"', "“", "「", "『")
_MAX_CLAIMS = 200


def _tagged(prompt: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>\n(.*)\n</{tag}>", prompt, re.DOTALL)
    return match.group(1) if match else None


def _claim(claim_type: str, subject_kind: str, subject: str, sentence: str, attributes: dict) -> dict:
    return {
        "claim_type": claim_type,
        "subject_kind": subject_kind,
        "subject": subject,
        "text": sentence,
        "evidence": sentence,
        "attributes": attributes,
    }


def extract(manuscript: str, known_characters: list[str], known_locations: list[str]) -> dict:
    sentences = [s.strip() for s in _SENTENCE_BREAK.split(manuscript) if s.strip()]
    counts: dict[str, int] = {}
    for word in _SUBJECT.findall(manuscript):
        if word not in _NOT_NAMES:
            counts[word] = counts.get(word, 0) + 1
    characters = list(dict.fromkeys(known_characters + [w for w, n in counts.items() if n >= 2]))
    locations = list(dict.fromkeys(known_locations + _PLACE.findall(manuscript)))

    claims = []
    for sentence in sentences:
        character = next((name for name in characters if name in sentence), None)
        location = next((name for name in locations if name in sentence), None)
        if character:
            attributes = {key: sentence for word, key in _APPEARANCE.items() if word in sentence}
            age = _AGE.search(sentence)
            if age:
                attributes["age"] = age.group(0)
            if attributes:
                claims.append(_claim("appearance", "character", character, sentence, attributes))
            if any(quote in sentence for quote in _QUOTES):
                claims.append(_claim("behavior", "character", character, sentence, {}))
            if any(word in sentence for word in _TIME_WORDS):
                claims.append(_claim("spacetime", "character", character, sentence, {}))
        if location:
            claims.append(_claim("location", "location", location, sentence, {}))
    return {"claims": claims[:_MAX_CLAIMS]}


class MockLLMClient(LLMClient):
    def complete(self, prompt: str, **kwargs) -> str:
        manuscript = _tagged(prompt, MANUSCRIPT_TAG)
        known = _tagged(prompt, KNOWN_ENTITIES_TAG)
        if manuscript is None or known is None:
            return "{}"
        entities = json.loads(known)
        result = extract(manuscript, entities.get("characters", []), entities.get("locations", []))
        return json.dumps(result, ensure_ascii=False)
