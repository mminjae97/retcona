"""Social login (design doc 3.1, 3.2).

Supported providers: Google, Kakao, Naver (OAuth 2.0)
Flow: receive auth code -> exchange token -> fetch profile -> look up/create user
      -> (if new signup) go to nickname setup screen -> issue JWE token

Note: social login never auto-fills nickname from the provider profile name.
      It is always entered directly by the user (3.6).
"""

# TODO: register per-provider clients using authlib.integrations.starlette_client, etc.
# - GOOGLE_OAUTH_CLIENT_ID / SECRET
# - KAKAO_OAUTH_CLIENT_ID / SECRET
# - NAVER_OAUTH_CLIENT_ID / SECRET
