"""소셜 로그인 (설계서 3.1, 3.2).

지원 제공자: Google, Kakao, Naver (OAuth 2.0)
흐름: 인가 코드 수신 -> 토큰 교환 -> 프로필 조회 -> 사용자 조회/생성
      -> (신규 가입이면) 필명 설정 화면으로 이동 -> JWE 토큰 발급

주의: 소셜 로그인은 프로필의 이름을 nickname으로 자동 채우지 않는다.
      항상 사용자에게 직접 입력받는다 (3.6).
"""

# TODO: authlib.integrations.starlette_client 등을 사용해 provider별 클라이언트 등록
# - GOOGLE_OAUTH_CLIENT_ID / SECRET
# - KAKAO_OAUTH_CLIENT_ID / SECRET
# - NAVER_OAUTH_CLIENT_ID / SECRET
