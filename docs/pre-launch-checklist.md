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

## 3. NLI model: hosting and attribution

**Now:** the appearance/location judgment uses the NLI model trained in
`ml/nli` (`mixed` in `ml/nli/RESULTS.md`), kept only on the machine that
trained it, in `ml/nli/runs/mixed` (not committed). A worker without that
directory falls back to a weaker public checkpoint (with a warning in its log).

**To do:**
- [ ] Host the model where production workers can load it, e.g. a private
      Hugging Face Hub repository (then `NLI_MODEL=<repo id>` plus an access
      token) or a GCS bucket (needs a download step at worker startup).
- [ ] Set `NLI_MODEL` in the production environment, and make sure production
      can't silently run on the fallback checkpoint (fail startup, or alert).
- [ ] Attribution: the training data (KorNLI, KLUE-NLI) is CC BY-SA 4.0. Credit
      both where the service lists its sources: KorNLI (Ham et al., 2020,
      kakaobrain/kor-nlu-datasets) and KLUE (Park et al., 2021,
      KLUE-benchmark/KLUE).

**Check:** a validation run on the production worker logs no fallback
warning, and the flags match what the same episode gives locally.

Code: `backend/infra/inference_client.py`, `ml/nli/`.

## 4. LLMs: choose and wire up the two models

**Now:** `LLM_PROVIDER=mock` — no model; `backend/infra/mock_llm.py` answers
the claim-extraction prompt from keyword rules and judges nothing. The
external and self-hosted clients are stubs that fail (`llm_failed`). The
project uses two models from the start (`backend/infra/llm_client.py`):
extraction (`LLM_MODEL_EXTRACTION`: most of the calls, a fast, cheaper model)
and judgment (`LLM_MODEL_JUDGMENT`: OOC, the final check of ambiguous
contradictions, spacetime assist — a stronger model).

**To do:**
- [ ] Choose the two models, trying each on real manuscripts: extraction —
      JSON kept, claims found, characters sharing a name told apart by their
      ref (`subject_ref`); judgment — OOC and ambiguous-contradiction calls.
- [ ] Implement `ExternalLLMClient.complete` (and a concurrency limit + retry
      backoff on rate limits, design doc 10.4).
- [ ] Set `LLM_PROVIDER=external`, `LLM_API_KEY`, `LLM_MODEL_EXTRACTION`,
      `LLM_MODEL_JUDGMENT` in the production environment (secret manager).

**Check:** a validation run on a real episode succeeds with the external
provider, its claims link to the right cards, and the provider's usage page
shows calls on both models once OOC judgment exists.

Code: `backend/infra/llm_client.py`, `backend/ai/llm.py`.
