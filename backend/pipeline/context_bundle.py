"""공유 컨텍스트 조회 (설계서 7.1, 7.3).

세 판단 모듈(외형/행동, 장소, 시공간)이 각자 따로 DB를 조회하지 않고,
이 함수가 한 번에 모아준 컨텍스트 번들을 공유해서 사용한다
(컨텍스트 사일로 방지, 7.3).

novel_id는 필수 인자로 받아 모든 하위 조회에 그대로 전달한다 (10.1).
"""


def get_context_bundle(novel_id: str, claims: list[dict]) -> dict:
    # TODO: characters, locations, world_settings, relations,
    #       character_state_history, location_state_history 등을
    #       pgvector 유사도 검색(novel_id 필터 필수, 10.1) + 리랭커로 관련 항목만 추려 반환
    raise NotImplementedError
