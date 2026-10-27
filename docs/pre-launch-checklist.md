# Pre-release checklist

Things to settle before the first public release of the Windows desktop app
(free and open source, design doc chapter 10). Each item says what is in
place now, what has to change, and how to check it.

The web service's items (a production Google OAuth client, real sending of
the signup verification email) are gone: the desktop app has no accounts, and
stage 6 of the roadmap removes login, signup and account deletion.

## 1. Licenses

**Now:** no license; the repository can't be reused by anyone yet.

**To do:**
- [ ] Choose the code license and add `LICENSE`. Apache-2.0 is a natural fit:
      the same as kiwipiepy and transformers, with a patent grant.
- [ ] Third-party notices for everything the installer bundles (Python and
      its packages, ONNX Runtime, Tauri, the frontend's npm packages), shown
      in the app's About screen.
- [ ] The models are released under CC BY-SA 4.0 (item 2), which is separate
      from the code license; say so in the README.

**Check:** the About screen lists every bundled component with its license;
a license scanner over the installer's contents finds nothing unlisted.

## 2. Models: ONNX export, publishing and attribution

**Now:** the NER, QA and NLI models are PyTorch checkpoints kept only on the
machine that trained them (`ml/ner/runs/klue`, `ml/qa/runs/klue`,
`ml/nli/runs/mixed`, not committed). A worker without the NLI model falls
back to a weaker public checkpoint; without NER or QA, extraction fails.

**To do:**
- [ ] Export the three to ONNX, and check that the ONNX models score the same
      as the PyTorch ones on the evaluation sets (`ml/extraction`,
      `ml/nli/RESULTS.md`), on the CPU and on a GPU. If they're quantized to
      shrink the download, measure the quantized ones the same way.
- [ ] Publish them in a public Hugging Face repository under CC BY-SA 4.0,
      with model cards that credit the training data: KorNLI (Ham et al.,
      2020, kakaobrain/kor-nlu-datasets) and KLUE (Park et al., 2021,
      KLUE-benchmark/KLUE; KLUE-NLI, KLUE-NER, KLUE-MRC). The base model,
      klue/roberta-base, is credited too.
- [ ] First-run download in the app: pinned versions, SHA-256 checks, resume
      after a dropped connection, a clear message offline. No silent fallback
      to a weaker model: a missing model is an error the author sees.
- [ ] The same credits in the app's About screen.

**Check:** on a clean Windows PC, the first run downloads the models,
verifies them, and validates an episode with the same flags as the
development machine.

Code: `backend/infra/inference_client.py`, `ml/nli/`, `ml/ner/`, `ml/qa/`.

## 3. LLM connections: terms and notices

**Now:** `LLM_PROVIDER=mock`, no model; the OOC judgment isn't built yet
(roadmap stage 5). The design (README part 2, chapter 3) is: Sign in with
ChatGPT (plan usage), an API key (Anthropic, OpenAI-compatible), or a local
OpenAI-compatible server.

**To do:**
- [ ] Re-read the providers' current terms right before release, since they
      have changed often: OpenAI's Sign in with ChatGPT for open-source /
      locally run apps (developers.openai.com/siwc), that Claude and Gemini
      subscriptions still can't be used by other apps, and how each free API
      tier uses its inputs (the Gemini API's free tier trains on them).
- [ ] The consent notice shown when a connection is first turned on, and the
      warning for tiers that train on inputs.
- [ ] Keys and tokens only in Windows Credential Manager; check that none end
      up in the database, logs or crash reports.

**Check:** connect each way once (ChatGPT, an Anthropic key, an
OpenAI-compatible key, Ollama), run an episode with an out-of-character
passage, and see an OOC flag; with the connection removed, the same episode
validates with "OOC not judged" and nothing else missing.

Code: `backend/infra/llm_client.py`, `backend/ai/llm.py`.

## 4. Installer, signing and updates

**Now:** no installer; the app runs from the development setup (Docker
PostgreSQL, `uvicorn`, `vite`).

**To do:**
- [ ] Code signing. Unsigned, the installer gets a SmartScreen warning that
      many authors won't click through. Options: a code-signing certificate,
      Azure Trusted Signing, or shipping unsigned with instructions at first.
- [ ] The updater's signing key: generated once, kept out of the repository
      (CI secret), backed up. Losing it means existing installs can't
      update.
- [ ] WebView2: present on Windows 11 and most Windows 10; the installer
      bootstraps it where it isn't.
- [ ] Uninstall keeps the data folder unless the author asks to remove it.

**Check:** install, update to a newer build and uninstall on a clean
Windows 10 and Windows 11 PC; the novels are still there after the update.

## 5. GPU and CPU

**Now:** development runs PyTorch on the CPU (`torch ...+cpu`).

**To do:**
- [ ] Before building on it, check the state of DirectML in ONNX Runtime
      (Microsoft has been moving Windows GPU inference to Windows ML) and
      pick the execution provider accordingly.
- [ ] Test on an NVIDIA GPU, an AMD or Intel GPU, and a PC with no usable GPU:
      the same flags on each, and a fallback to the CPU when the GPU fails.
- [ ] Measure a typical episode's validation time on the CPU, and say in the
      README what to expect.

**Check:** the settings screen shows which device ran the last validation,
and CPU only gives the same results as the GPU.
