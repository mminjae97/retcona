"""LLMClient interface (design doc 10.4.3).

Used for OOC behavior judgment, final verification of ambiguous contradictions,
claim extraction, etc. (chapter 5, 7.2). LLM_PROVIDER=external|self_hosted|mock
selects the implementation; mock (infra/mock_llm.py) is a development stand-in
until a model is chosen.
"""

from abc import ABC, abstractmethod


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
    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def complete(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError("No self-hosted LLM is wired up yet; set LLM_PROVIDER=mock for development")


def get_llm_client() -> LLMClient:
    import os

    provider = os.environ.get("LLM_PROVIDER", "external")
    if provider == "mock":
        # Imported here: it reads ai/llm.py's prompt format, and ai/llm.py imports this module.
        from infra.mock_llm import MockLLMClient

        return MockLLMClient()
    if provider == "self_hosted":
        return SelfHostedLLMClient(endpoint=os.environ.get("LLM_ENDPOINT", ""))
    return ExternalLLMClient(
        api_key=os.environ.get("LLM_API_KEY", ""),
        model=os.environ.get("LLM_MODEL", ""),
    )
