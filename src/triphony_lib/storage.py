"""Provider-neutral private artifact storage contracts."""

from __future__ import annotations

import hashlib
import mimetypes
import pathlib
import re
import shutil
from dataclasses import dataclass
from typing import Any, Protocol

from triphony_lib.observability import metric_observe, span


class ArtifactStoreError(RuntimeError):
    """Safe storage-boundary failure."""


@dataclass(frozen=True)
class ArtifactMetadata:
    key: str
    content_type: str
    content_length: int
    checksum_sha256: str
    version_id: str | None = None


class ArtifactStore(Protocol):
    def put(self, source: pathlib.Path, *, key: str, content_type: str, metadata: dict[str, str] | None = None) -> ArtifactMetadata: ...
    def head(self, key: str) -> ArtifactMetadata: ...
    def signed_get_url(self, key: str, *, expires_in: int) -> str | None: ...


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


def safe_artifact_key(scene_id: str, asset_version_id: str, filename: str, *, prefix: str = "triphony") -> str:
    if not all(re.fullmatch(r"[A-Za-z0-9-]{1,128}", value) for value in (scene_id, asset_version_id)):
        raise ArtifactStoreError("invalid artifact identity")
    extension = pathlib.PurePath(filename).suffix.lower()
    if extension not in {".mp4", ".wav", ".mp3", ".png", ".jpg", ".json", ".txt"}:
        raise ArtifactStoreError("unsupported artifact extension")
    key = "/".join(part.strip("/") for part in (prefix, scene_id, asset_version_id + extension) if part)
    if not _SAFE_COMPONENT.fullmatch(key):
        raise ArtifactStoreError("unsafe artifact key")
    return key


def _checksum(source: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalArtifactStore:
    def __init__(self, root: pathlib.Path, *, max_object_size: int = 512 * 1024 * 1024) -> None:
        self.root = root.resolve()
        self.max_object_size = max_object_size
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> pathlib.Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ArtifactStoreError("artifact path escaped private root")
        return path

    def put(self, source: pathlib.Path, *, key: str, content_type: str, metadata: dict[str, str] | None = None) -> ArtifactMetadata:
        with span("storage.put", backend="local", key=key, content_type=content_type):
            source = source.resolve()
            if not source.is_file() or source.stat().st_size > self.max_object_size:
                raise ArtifactStoreError("artifact is missing or exceeds the configured size")
            target = self._path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copyfile(source, temporary)
            temporary.replace(target)
            return ArtifactMetadata(key, content_type, target.stat().st_size, _checksum(target))

    def head(self, key: str) -> ArtifactMetadata:
        with span("storage.head", backend="local", key=key):
            path = self._path(key)
            if not path.is_file():
                raise ArtifactStoreError("artifact not found")
            return ArtifactMetadata(key, mimetypes.guess_type(path.name)[0] or "application/octet-stream", path.stat().st_size, _checksum(path))

    def signed_get_url(self, key: str, *, expires_in: int) -> str | None:
        with span("storage.signed_get_url", backend="local", key=key):
            self._path(key)
            return None


class S3ArtifactStore:
    def __init__(self, *, bucket: str, region: str, prefix: str = "triphony", encryption: str = "AES256", kms_key_id: str | None = None, client: Any | None = None, max_object_size: int = 512 * 1024 * 1024, multipart_threshold_bytes: int = 64 * 1024 * 1024, request_timeout_seconds: int = 120) -> None:
        if not bucket or not region:
            raise ArtifactStoreError("S3 bucket and region are required")
        self.bucket = bucket
        self.region = region
        self.prefix = prefix.strip("/")
        self.encryption = encryption
        self.kms_key_id = kms_key_id
        self.max_object_size = max_object_size
        self.multipart_threshold_bytes = multipart_threshold_bytes
        self.request_timeout_seconds = request_timeout_seconds
        self.client = client

    def _key(self, key: str) -> str:
        candidate = key.strip("/")
        if not candidate or any(part in {"", ".", ".."} for part in pathlib.PurePosixPath(candidate).parts):
            raise ArtifactStoreError("unsafe S3 object key")
        if not _SAFE_COMPONENT.fullmatch(candidate):
            raise ArtifactStoreError("unsafe S3 object key")
        return "/".join(part for part in (self.prefix, candidate) if part)

    def _client(self) -> Any:
        if self.client is None:
            import boto3
            from botocore.config import Config
            self.client = boto3.client(
                "s3",
                region_name=self.region,
                config=Config(
                    connect_timeout=self.request_timeout_seconds,
                    read_timeout=self.request_timeout_seconds,
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        return self.client

    def put(self, source: pathlib.Path, *, key: str, content_type: str, metadata: dict[str, str] | None = None) -> ArtifactMetadata:
        with span("storage.put", backend="s3", key=key, content_type=content_type):
            source = source.resolve()
            if not source.is_file() or source.stat().st_size > self.max_object_size:
                raise ArtifactStoreError("artifact is missing or exceeds the configured size")
            checksum = _checksum(source)
            extra_metadata = {**(metadata or {}), "checksum-sha256": checksum}
            extra: dict[str, Any] = {"ContentType": content_type, "Metadata": extra_metadata, "ServerSideEncryption": self.encryption}
            if self.encryption == "aws:kms" and self.kms_key_id:
                extra["SSEKMSKeyId"] = self.kms_key_id
            try:
                object_key = self._key(key)
                from boto3.s3.transfer import TransferConfig
                self._client().upload_file(
                    str(source), self.bucket, object_key, ExtraArgs=extra,
                    Config=TransferConfig(multipart_threshold=self.multipart_threshold_bytes),
                )
                response = self._client().head_object(Bucket=self.bucket, Key=object_key)
            except Exception as error:
                raise ArtifactStoreError("S3 artifact upload or verification failed") from error
            length = int(response.get("ContentLength", -1))
            remote_checksum = str(response.get("Metadata", {}).get("checksum-sha256", ""))
            if length != source.stat().st_size or remote_checksum != checksum:
                raise ArtifactStoreError("S3 artifact checksum or size verification failed")
            metric_observe("triphony.storage.bytes", float(length), backend="s3")
            return ArtifactMetadata(key, content_type, length, checksum, response.get("VersionId"))

    def head(self, key: str) -> ArtifactMetadata:
        with span("storage.head", backend="s3", key=key):
            try:
                response = self._client().head_object(Bucket=self.bucket, Key=self._key(key))
            except Exception as error:
                raise ArtifactStoreError("S3 artifact metadata lookup failed") from error
            length = int(response["ContentLength"])
            metric_observe("triphony.storage.bytes", float(length), backend="s3")
            return ArtifactMetadata(key, response.get("ContentType", "application/octet-stream"), length, response.get("Metadata", {}).get("checksum-sha256", ""), response.get("VersionId"))

    def signed_get_url(self, key: str, *, expires_in: int) -> str:
        with span("storage.signed_get_url", backend="s3", key=key):
            if not 1 <= expires_in <= 3600:
                raise ArtifactStoreError("presigned URL expiration must be between 1 and 3600 seconds")
            try:
                return str(self._client().generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": self._key(key)}, ExpiresIn=expires_in))
            except Exception as error:
                raise ArtifactStoreError("S3 signed delivery failed") from error
