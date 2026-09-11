"""원고에서 검증 대상 클레임을 추출한다 (설계서 7.1 첫 단계).

입력: novel_id, episode_id, 원고 원문
출력: Claim 목록 (claim_type: 외형 | 행동(OOC) | 장소 | 시공간)

이후 엔티티 매칭(7.4)에서 클레임에 등장하는 인물·장소명을
기존 characters/locations와 대조해 신규 엔티티 자동 등록 여부를 결정한다.
"""


def extract_claims(novel_id: str, episode_id: str, manuscript: str) -> list[dict]:
    # TODO: LLM 기반 클레임 추출 구현
    raise NotImplementedError
