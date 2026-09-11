"""설정 보완 후 재검증 (설계서 7.5).

전체 파이프라인을 다시 돌리지 않고, 플래그를 발생시킨 판단 모듈만
새 컨텍스트 번들로 재실행한다 (비용 절감). 재검증도 작업 큐를 거쳐 비동기 처리한다 (10.2).

해소되면 status를 resolved_by_revalidation으로 전환하고,
어떤 설정이 추가되어 해소됐는지 근거를 남긴다 (이후 오탐 감소 참고용).
"""


def revalidate_flag(novel_id: str, flag_id: str) -> dict:
    # TODO:
    #   1. flag_id로부터 error_type(외형/장소/시공간)을 확인해 해당 judge 함수만 호출
    #   2. 모순 해소 -> status=resolved_by_revalidation, 해소 근거 기록
    #   3. 여전히 모순 -> status는 open 유지, evidence_text 갱신
    raise NotImplementedError
