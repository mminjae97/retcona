"""LLMClient interface (design doc 10.4.3).

Two models, one per purpose (chapter 5), each named in its own setting:
- extraction (LLM_MODEL_EXTRACTION): claim extraction — the bulk of the calls
  (every episode's whole manuscript, on every run), fact-finding in a fixed
  JSON shape; a fast, cheaper model.
- judgment (LLM_MODEL_JUDGMENT): OOC behavior judgment, the final check of
  contradictions NLI finds ambiguous, spacetime assist — few calls, reasoning
  over settings and context; a stronger model.
LLM_PROVIDER=external|self_hosted|mock selects the implementation for both;
mock (infra/mock_llm.py) is a development stand-in until models are chosen.
"""

import os
from abc import ABC, abstractmethod
from typing import Literal

LLMPurpose = Literal["extraction", "judgment"]


class LLMClient(ABC):
    @abstractmethod
    def complete(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError


class ExternalLLMClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        # TODO: initialize the external LLM API client to use (model TBD, chapter 5)

    def complete(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError("No external LLM is wired up yet (model TBD); set LLM_PROVIDER=mock for development")


class SelfHostedLLMClient(LLMClient):
    def __init__(self, endpoint: str, model: str):
        self.endpoint = endpoint
        self.model = model

    def complete(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError("No self-hosted LLM is wired up yet; set LLM_PROVIDER=mock for development")


def get_llm_client(purpose: LLMPurpose) -> LLMClient:
    provider = os.environ.get("LLM_PROVIDER", "external")
    model = os.environ.get(f"LLM_MODEL_{purpose.upper()}", "")
    if provider == "mock":
        # Imported here: it reads ai/llm.py's prompt format, and ai/llm.py imports this module.
        from infra.mock_llm import MockLLMClient

        return MockLLMClient()
    if provider == "self_hosted":
        return SelfHostedLLMClient(endpoint=os.environ.get("LLM_ENDPOINT", ""), model=model)
    return ExternalLLMClient(api_key=os.environ.get("LLM_API_KEY", ""), model=model)
