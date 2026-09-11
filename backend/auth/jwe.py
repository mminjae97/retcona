"""인증 토큰 발급/검증 (설계서 3.3 JWE).

구조 (Nested JWT):
  1. 클레임(user_id, novel 권한 등)을 JWT로 서명 (JWS) -> 무결성 보장
  2. 서명된 토큰 전체를 JWE로 암호화 -> 기밀성 보장

알고리즘 예시: 서명 RS256 / 키 관리 RSA-OAEP-256 / 콘텐츠 암호화 A256GCM
서버만 복호화 키를 보유하며, 클라이언트는 암호화된 토큰만 저장·전달한다.
"""

# TODO: python-jose 또는 authlib의 jwe 모듈을 사용해 아래 두 함수를 구현
# - issue_token(user_id: str, claims: dict) -> str
# - decode_token(token: str) -> dict
