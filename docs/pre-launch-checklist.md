# Pre-launch checklist

Things deliberately left in their development setup, to be finished in the
project's wrap-up phase before real users sign up. Each item says what is in
place now, what has to change, and how to check it.

## 1. Google login: production OAuth client

**Now:** a development OAuth client (Google Cloud Console → APIs & Services →
Credentials), redirect URI `http://localhost:5173/auth/google/callback`, its
values in the local `.env` (`GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`). The client may be
replaced with a different one (or project) before launch.

**To do:**
- [ ] Create (or switch to) the production OAuth client, type "Web application".
- [ ] Add the production redirect URI, `https://<frontend domain>/auth/google/callback`,
      under "Authorized redirect URIs" — it must match `GOOGLE_OAUTH_REDIRECT_URI`
      exactly (scheme, host, path, no trailing slash).
- [ ] Set the three `GOOGLE_OAUTH_*` values in the production environment
      (secret manager, not a committed file). Remove the development client's
      values from anywhere they were copied.
- [ ] OAuth consent screen: move the app from **Testing** to **In production**.
      While it is in Testing, only the listed test users can sign in; everyone
      else gets an "access blocked" error from Google. The requested scopes
      are `openid email` only, so no Google verification review should be
      needed, but check the console's current rules.
- [ ] Fill in the consent screen's app name, support email, logo, and links
      to the privacy policy / terms (Google shows them to users).

**Check:** `GET /auth/google/config` returns `enabled: true` with the
production client id and redirect URI; sign in with an account that is not a
test user.

Code: `backend/auth/oauth.py`, `frontend/src/utils/googleAuth.ts`.

## 2. Signup verification email: real sending

**Now:** `EMAIL_PROVIDER=console` — no email is sent; the 6-digit code is
written to the API server's log. That is only acceptable locally: anyone who
can read the log can complete any signup.

**To do:**
- [ ] Choose the sending service (an SMTP relay: Gmail/Google Workspace, Amazon
      SES, SendGrid, ...). `infra/email_client.py` speaks plain SMTP, so any of
      them works through configuration; a provider-specific HTTP API would be a
      new `EmailClient` implementation there.
- [ ] Set `EMAIL_PROVIDER=smtp` and `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`,
      `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` in the production
      environment (see `.env.example`).
- [ ] Sender domain: set up SPF, DKIM and DMARC for the `SMTP_FROM` domain, so
      the codes don't land in spam.
- [ ] Make sure production can never start with `EMAIL_PROVIDER=console`
      (e.g. fail startup, or at least alert, when it is console outside local
      development).

**Check:** request a code for a real inbox (Gmail and Naver mail, at least),
confirm it arrives within a minute and not in spam, and that a failure at the
mail server shows the "인증 메일을 보내지 못했습니다" message.

Code: `backend/infra/email_client.py`, `backend/auth/email_verification.py`.
