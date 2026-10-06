"""S3-compatible object storage client (MinIO by default; see techstack.md §7).

boto3 is synchronous; every method wraps its blocking call in
`asyncio.to_thread` so it's safe to await from async service code
(style_guide.md §A.1: no blocking I/O inside `async def`).
"""

from __future__ import annotations

import asyncio

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from vms_common.storage.uri import parse_uri

DEFAULT_PRESIGN_EXPIRY_SECONDS = 900  # NFR-SEC-02: presigned URLs <= 15 min


class S3Client:
    """Thin async wrapper over boto3 for one S3-compatible endpoint."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        public_endpoint_url: str = "",
    ) -> None:
        def make(endpoint: str):
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=BotoConfig(signature_version="s3v4"),
            )

        self._client = make(endpoint_url)
        # Presigning is a local computation, so a second client for the browser-facing host
        # costs nothing; it is only built when that host differs.
        self._signer = make(public_endpoint_url) if public_endpoint_url else self._client

    async def put_bytes(self, uri: str, data: bytes, *, content_type: str | None = None) -> None:
        """Upload raw bytes to `uri`."""
        loc = parse_uri(uri)
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(
            self._client.put_object, Bucket=loc.bucket, Key=loc.key, Body=data, **extra
        )

    async def get_bytes(self, uri: str) -> bytes:
        """Download `uri` fully into memory. Use for small objects (twins, JSON)."""
        loc = parse_uri(uri)
        response = await asyncio.to_thread(self._client.get_object, Bucket=loc.bucket, Key=loc.key)
        return await asyncio.to_thread(response["Body"].read)

    async def exists(self, uri: str) -> bool:
        """Whether the object is there (a HEAD request); false once retention has removed it."""
        loc = parse_uri(uri)
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=loc.bucket, Key=loc.key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code", "") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    async def upload_file(self, uri: str, local_path: str) -> None:
        """Upload a local file to `uri`. Use for segments/large blobs."""
        loc = parse_uri(uri)
        await asyncio.to_thread(self._client.upload_file, local_path, loc.bucket, loc.key)

    async def download_file(self, uri: str, local_path: str) -> None:
        """Download `uri` to a local file. Use for segments/large blobs."""
        loc = parse_uri(uri)
        await asyncio.to_thread(self._client.download_file, loc.bucket, loc.key, local_path)

    async def presign_get(
        self, uri: str, *, expires_in: int = DEFAULT_PRESIGN_EXPIRY_SECONDS
    ) -> str:
        """Presigned GET URL for `uri`. `expires_in` is clamped to <= 900s (NFR-SEC-02)."""
        loc = parse_uri(uri)
        expires_in = min(expires_in, DEFAULT_PRESIGN_EXPIRY_SECONDS)
        return await asyncio.to_thread(
            self._signer.generate_presigned_url,
            "get_object",
            Params={"Bucket": loc.bucket, "Key": loc.key},
            ExpiresIn=expires_in,
        )

    async def ensure_bucket(self, bucket: str) -> None:
        """Create `bucket` if it doesn't exist (idempotent; call at startup)."""
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=bucket)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code not in {"404", "NoSuchBucket"}:
                raise
            await asyncio.to_thread(self._client.create_bucket, Bucket=bucket)
