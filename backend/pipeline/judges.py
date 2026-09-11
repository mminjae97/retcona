"""판단 모듈 3종 (설계서 7.2).

동일 인터페이스(claims + context_bundle 입력 -> flags 출력)를 공유해
병렬 실행과 모듈 교체가 용이하도록 한다 (6.2).

| 모듈 | 주요 입력 필드 | 판단 방식 |
|---|---|---|
| 외형/행동 위반 | fixed_attrs, latest_mutable_state, personality, world_settings | 외형: NLI / 행동(OOC): LLM |
| 장소 오류 | fixed_attrs(지형), relations(거리) | NLI + 규칙 기반 거리 계산 |
| 시공간 모순 | last_known_position, state_history, relations | 규칙 기반 시간·거리 검증 + LLM 보조 |
"""


def judge_appearance_and_behavior(claims: list[dict], context_bundle: dict) -> list[dict]:
    # TODO: 외형은 NLI, 행동(OOC)은 LLM + 성격·말투 프로파일 기반 추론
    raise NotImplementedError


def judge_location(claims: list[dict], context_bundle: dict) -> list[dict]:
    # TODO: NLI + 규칙 기반 거리 계산
    raise NotImplementedError


def judge_timeline(claims: list[dict], context_bundle: dict) -> list[dict]:
    # TODO: 규칙 기반 시간·거리 검증 + LLM 보조
    raise NotImplementedError
