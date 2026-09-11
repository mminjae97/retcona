"""StorageClient interface (design doc 10.4.3).

Used for storing binary files such as character illustrations (chapter 9).
Production (GCP): GCSStorageClient / Local dev: LocalStorageClient
"""

from abc import ABC, abstractmethod


class StorageClient(ABC):
    @abstractmethod
    def upload(self, key: str, data: bytes) -> str:
        """Store the data and return an accessible URL/path."""

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
        # TODO: initialize the google-cloud-storage client

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
