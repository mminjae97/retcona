"""결과 병합 및 자동 반영 (설계서 7.1, 7.3, 7.4).

- merge_and_dedupe: 세 판단 모듈의 결과를 병합하고 동일 원인 오류의 중복 탐지를 제거
- 모순으로 플래그되지 않은 클레임은 character_state_history/location_state_history에
  자동으로 누적 반영한다 (7.4). 모순으로 플래그된 클레임만 작가 확인 후 반영한다.
"""


def merge_and_dedupe(flags_by_module: list[list[dict]]) -> list[dict]:
    # TODO: 동일 원인 오류 중복 제거 후 신뢰도순 정렬 (2.5)
    raise NotImplementedError


def auto_apply_non_contradicting_claims(novel_id: str, claims: list[dict], flags: list[dict]) -> None:
    # TODO: flags에 포함되지 않은 claim만 state_history에 자동 반영 (7.4)
    raise NotImplementedError
