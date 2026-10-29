"""India/Development Stratus REST adapter, without the incompatible Catalyst SDK.

Only dedicated application OAuth credentials are supported. No CLI credential
store access, public buckets, S3 assumptions, or unbounded media buffering.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
import shutil
import tempfile
import time
from urllib.parse import unquote, urlsplit

import httpx

from pixl.core.config import settings
from pixl.core.exceptions import UnprocessableError
from pixl.core.storage_provider import StorageProvider, StorageUnavailable


class _RedactQuery(logging.Filter):
    """HTTPX INFO logging otherwise prints signed URL query strings."""
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(value.copy_with(query=None) if isinstance(value, httpx.URL)
                                else value for value in record.args)
        return True


if not any(isinstance(f, _RedactQuery) for f in logging.getLogger("httpx").filters):
    logging.getLogger("httpx").addFilter(_RedactQuery())


@dataclass(frozen=True)
class StratusConfig:
    project: str
    organization: str
    bucket: str
    namespace: str
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)
    temp_path: str = ""


@lru_cache(maxsize=4)
def _configured(config):
    return StratusStorage(config)


def configured_stratus():
    settings.validate_stratus()
    return _configured(StratusConfig(
        settings.STRATUS_PROJECT_ID, settings.STRATUS_ORGANIZATION_ID,
        settings.STRATUS_BUCKET, settings.STRATUS_NAMESPACE,
        settings.STRATUS_CLIENT_ID.get_secret_value(),
        settings.STRATUS_CLIENT_SECRET.get_secret_value(),
        settings.STRATUS_REFRESH_TOKEN.get_secret_value(), settings.MEDIA_TEMP_PATH))


class StratusStorage(StorageProvider):
    direct_upload = True
    api_origin = "https://api.catalyst.zoho.in"
    accounts_origin = "https://accounts.zoho.in"

    def __init__(self, config: StratusConfig, *, transport=None):
        self.config = config
        self.origin = f"https://{config.bucket}-development.zohostratus.in"
        self._transport = transport  # Dependency injection for offline contract tests.
        self._token = ""
        self._token_expires = 0.0

    def _client(self):
        return httpx.AsyncClient(transport=self._transport, follow_redirects=False,
                                 trust_env=False, timeout=httpx.Timeout(15, connect=5))

    def _key(self, key):
        # Logical keys contain only server-generated tenant/ticket/lease identifiers.
        if not re.fullmatch(r"(?:quarantine|published)/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", key):
            raise UnprocessableError("Invalid storage key")
        return f"{self.config.namespace}/{key}"

    async def _json(self, method, url, **kwargs):
        try:
            async with self._client() as client:
                async with client.stream(method, url, **kwargs) as response:
                    if response.status_code == 404 and kwargs.get("params", {}).get("object_key"):
                        return None
                    if not 200 <= response.status_code < 300:
                        raise StorageUnavailable()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 1024 * 1024:
                            raise StorageUnavailable()
                    data = json.loads(content)
                    if not isinstance(data, dict):
                        raise StorageUnavailable()
                    return data
        except (httpx.HTTPError, ValueError, TypeError):
            # HTTP exceptions can embed full signed URLs or OAuth response bodies.
            raise StorageUnavailable() from None

    async def _access_token(self):
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        data = await self._json("POST", self.accounts_origin + "/oauth/v2/token", data={
            "grant_type": "refresh_token", "client_id": self.config.client_id,
            "client_secret": self.config.client_secret, "refresh_token": self.config.refresh_token})
        token = data.get("access_token")
        lifetime = data.get("expires_in", 3600)
        if not isinstance(token, str) or not token or not isinstance(lifetime, (int, float)) or lifetime <= 60:
            raise StorageUnavailable()
        self._token = token
        self._token_expires = time.monotonic() + min(lifetime, 3600) - 60
        return token

    async def _api(self, method, path, *, params=None, **kwargs):
        token = await self._access_token()
        data = await self._json(method,
            f"{self.api_origin}/baas/v1/project/{self.config.project}{path}",
            headers={"Authorization": f"Zoho-oauthtoken {token}",
                     "CATALYST-ORG": self.config.organization, "Environment": "Development"},
            params={"bucket_name": self.config.bucket, **(params or {})}, **kwargs)
        if data is None:
            return None
        if data.get("status") not in (None, "success") or "data" not in data:
            raise StorageUnavailable()
        return data["data"]

    async def _signed(self, key, action, ttl):
        remote_key = self._key(key)
        data = await self._api(action, "/bucket/object/signed-url", params={
            "object_key": remote_key, "expiry_in_seconds": max(30, min(int(ttl), 604800))})
        url = data.get("signature") if isinstance(data, dict) else None
        if not isinstance(url, str):
            raise StorageUnavailable()
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme == "https" and parsed.netloc == urlsplit(self.origin).netloc
                     and not parsed.fragment and parsed.query
                     and unquote(parsed.path) == "/_signed/" + remote_key
                     and not any(ord(c) < 33 or ord(c) == 127 for c in url))
        except ValueError:
            valid = False
        if not valid:
            raise StorageUnavailable()
        return url

    async def upload_url(self, ticket_id, key, ttl):
        if not key.startswith("quarantine/"):
            raise UnprocessableError("Uploads must target quarantine")
        return await self._signed(key, "PUT", ttl)

    async def size(self, key):
        data = await self._api("GET", "/bucket/object", params={"object_key": self._key(key)})
        if data is None:
            return None
        if not isinstance(data, dict):
            raise StorageUnavailable()
        size = data.get("size")
        if isinstance(size, bool) or not str(size).isdigit():
            raise StorageUnavailable()
        return int(size)

    @asynccontextmanager
    async def materialize(self, key, expected_size):
        if not 0 < expected_size <= settings.MAX_UPLOAD_BYTES:
            raise UnprocessableError("Invalid media size")
        if await self.size(key) != expected_size:
            raise UnprocessableError("Uploaded content is missing or has changed")
        url = await self._signed(key, "GET", 300)
        try:
            with tempfile.TemporaryDirectory(prefix="pixl-inspect-", dir=self.config.temp_path or None) as directory:
                if shutil.disk_usage(directory).free < expected_size + 64 * 1024 * 1024:
                    raise StorageUnavailable()
                source = Path(directory) / "source"
                # Deadline bounds a slow trickle; Content-Length is only a hint.
                async with asyncio.timeout(90):
                    async with self._client() as client:
                        async with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
                            if response.status_code != 200 or response.headers.get("content-encoding", "identity") != "identity":
                                raise StorageUnavailable()
                            size = 0
                            with source.open("wb") as output:
                                async for chunk in response.aiter_raw(chunk_size=65536):
                                    size += len(chunk)
                                    if size > expected_size:
                                        raise UnprocessableError("Uploaded size does not match the ticket")
                                    await asyncio.to_thread(output.write, chunk)
                            if size != expected_size:
                                raise UnprocessableError("Uploaded size does not match the ticket")
                # Publish this exact snapshot after checksum/decoder inspection.
                # A later replay of the quarantine PUT cannot modify this file.
                yield source
        except (httpx.HTTPError, TimeoutError, OSError):
            raise StorageUnavailable() from None

    async def publish(self, key, source, mime, lease):
        if not key.startswith("published/"):
            raise UnprocessableError("Publication must target published storage")
        url = await self._signed(key, "PUT", 300)
        length = source.stat().st_size
        async def chunks():
            with source.open("rb") as content:
                while block := await asyncio.to_thread(content.read, 65536):
                    yield block
        try:
            async with asyncio.timeout(60):
                async with self._client() as client:
                    async with client.stream("PUT", url, content=chunks(), headers={
                            "Content-Type": mime, "Content-Length": str(length),
                            "overwrite": "false", "compress": "false"}) as response:
                        if response.status_code != 200:
                            raise StorageUnavailable()
            if await self.size(key) != length:
                raise StorageUnavailable()
        except (httpx.HTTPError, TimeoutError, OSError):
            raise StorageUnavailable() from None

    async def delete(self, key):
        # This API may schedule deletion. Do not release quota until GET confirms
        # absence; a transport error or permission denial is never absence.
        await self._api("PUT", "/bucket/object", json={"objects": [{"key": self._key(key)}]})
        return await self.size(key) is None

    async def reconcile(self, quarantine, published, keep, cutoff: datetime):
        remote_prefix = self._key(published).rsplit(".", 1)[0] + "."
        data = await self._api("GET", "/bucket/objects", params={
            "prefix": remote_prefix, "max_keys": 100})
        if not isinstance(data, dict) or not isinstance(data.get("contents"), list):
            raise StorageUnavailable()
        complete = await self.delete(quarantine)
        protected = {self._key(key) for key in keep}
        for obj in data["contents"]:
            remote_key = obj.get("key") if isinstance(obj, dict) else None
            if not isinstance(remote_key, str) or not remote_key.startswith(remote_prefix):
                raise StorageUnavailable()
            if remote_key not in protected:
                logical_key = remote_key[len(self.config.namespace) + 1:]
                complete = await self.delete(logical_key) and complete
        # A bounded page is intentional. Subsequent maintenance passes drain
        # orphan attempts; never acknowledge cleanup with an incomplete listing.
        return complete and data.get("truncated") in (False, "false")

    async def download_url(self, key, ttl):
        if not key.startswith("published/"):
            raise UnprocessableError("Quarantine is private")
        return await self._signed(key, "GET", ttl)
