"""StorageClient 인터페이스 (설계서 10.4.3).

캐릭터 일러스트(9장) 등 바이너리 파일 저장에 사용한다.
운영(GCP): GCSStorageClient / 로컬 개발: LocalStorageClient
"""

from abc import ABC, abstractmethod


class StorageClient(ABC):
    @abstractmethod
    def upload(self, key: str, data: bytes) -> str:
        """저장하고 접근 가능한 URL/경로를 반환한다."""

    @abstractmethod
    def download(self, key: str) -> bytes:
        raise NotImplementedError


class LocalStorageClient(StorageClient):
    def __init__(self, base_dir: str = "./.local_storage"):
        self.base_dir = base_dir

    def upload(self, key: str, data: bytes) -> str:
        raise NotImplementedError

    def download(self, key: str) -> bytes:
        raise NotImplementedError


class GCSStorageClient(StorageClient):
    def __init__(self, bucket: str):
        self.bucket = bucket
        # TODO: google-cloud-storage 클라이언트 초기화

    def upload(self, key: str, data: bytes) -> str:
        raise NotImplementedError

    def download(self, key: str) -> bytes:
        raise NotImplementedError


def get_storage_client() -> StorageClient:
    import os

    provider = os.environ.get("STORAGE_PROVIDER", "local")
    if provider == "gcs":
        return GCSStorageClient(bucket=os.environ["GCS_BUCKET"])
    return LocalStorageClient()
