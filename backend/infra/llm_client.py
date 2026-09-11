"""LLMClient 인터페이스 (설계서 10.4.3).

OOC 행동 판단, 애매한 모순 최종 검증, 클레임 추출 등에 사용 (5장, 7.2).
LLM_PROVIDER=external|self_hosted 로 구현체를 고른다.
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
        # TODO: 사용할 외부 LLM API 클라이언트 초기화 (모델 미정, 5장)

    def complete(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError


class SelfHostedLLMClient(LLMClient):
    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def complete(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError


def get_llm_client() -> LLMClient:
    import os

    provider = os.environ.get("LLM_PROVIDER", "external")
    if provider == "self_hosted":
        return SelfHostedLLMClient(endpoint=os.environ.get("LLM_ENDPOINT", ""))
    return ExternalLLMClient(
        api_key=os.environ.get("LLM_API_KEY", ""),
        model=os.environ.get("LLM_MODEL", ""),
    )
