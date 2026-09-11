"""Auth token issuance/verification (design doc 3.3 JWE).

Structure (Nested JWT):
  1. Sign the claims (user_id, novel permissions, etc.) as a JWT (JWS) -> guarantees integrity
  2. Encrypt the whole signed token as JWE -> guarantees confidentiality

Algorithm example: signing RS256 / key management RSA-OAEP-256 / content encryption A256GCM
Only the server holds the decryption key; the client only stores/sends the encrypted token.
"""

# TODO: implement the two functions below using python-jose or authlib's jwe module
# - issue_token(user_id: str, claims: dict) -> str
# - decode_token(token: str) -> dict
