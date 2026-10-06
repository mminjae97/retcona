"""Development stand-in for the LLM (LLM_PROVIDER=mock).

No model and no network, and it judges nothing: every prompt gets an empty
JSON object. The LLM is used for OOC judgment only (design doc 7.2), which
isn't built yet; claim extraction doesn't use it (7.1.1).
"""

from infra.llm_client import LLMClient


class MockLLMClient(LLMClient):
    def complete(self, prompt: str, **kwargs) -> str:
        return "{}"
