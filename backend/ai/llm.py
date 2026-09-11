"""LLM 래퍼 (설계서 5장, 7.2).

OOC 행동 판단, 애매한 모순 최종 검증, 클레임 추출에 사용.
실제 provider(external/self_hosted)는 infra.llm_client가 담당한다.
"""

from infra.llm_client import get_llm_client


def judge_ooc(character_profile: dict, manuscript_excerpt: str) -> dict:
    prompt = f"성격/말투 프로파일: {character_profile}\n\n다음 서술이 위 프로파일과 어긋나는지 판단하라:\n{manuscript_excerpt}"
    result = get_llm_client().complete(prompt)
    # TODO: LLM 응답 파싱
    return {"raw": result}
