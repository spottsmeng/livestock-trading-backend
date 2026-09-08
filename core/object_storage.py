"""Original-file retention (§7.2 pt 9, §8). Every committed OrderSnapshot's
source .xlsx is persisted here, alongside its SHA-256 (stored on the model,
not here), so every submission stays provable.

Two implementations behind one small protocol:
- `LocalFilesystemObjectStorage` — the documented local-dev/CI stand-in.
- `S3CompatibleObjectStorage` — the real answer for the Railway deployment
  (which has no native blob storage of its own): any S3-compatible bucket
  via boto3 (Apache-2.0/FOSS regardless of which provider backs the
  bucket — Cloudflare R2, Backblaze B2, self-hosted MinIO, or AWS S3).
"""

from pathlib import Path
from typing import Protocol

from core.config import settings


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalFilesystemObjectStorage:
    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)

    def _path_for(self, key: str) -> Path:
        path = self._base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put(self, key: str, data: bytes) -> None:
        self._path_for(key).write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()


class S3CompatibleObjectStorage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        import boto3

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
        )

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()


def get_object_storage() -> ObjectStorage:
    if settings.object_storage_backend == "s3":
        return S3CompatibleObjectStorage(
            bucket=settings.object_storage_bucket,
            endpoint_url=settings.object_storage_endpoint_url,
            region=settings.object_storage_region,
            access_key_id=settings.object_storage_access_key_id,
            secret_access_key=settings.object_storage_secret_access_key,
        )
    return LocalFilesystemObjectStorage(settings.object_storage_local_dir)
