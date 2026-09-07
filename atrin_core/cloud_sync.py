"""Encrypted, vendor-neutral checkpoint synchronization."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlparse

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .database import AtrinDatabase
from .models import SyncConfig, SyncDirection, SyncStatus


class StorageProvider(Protocol):
    async def upload(self, remote_id: str, payload: bytes) -> None: ...
    async def download(self, remote_id: str) -> bytes: ...


class HTTPStorageProvider:
    """Uses standard HTTP PUT/GET for S3-compatible and WebDAV endpoints."""

    def __init__(self, base_url: str, headers: dict[str, str] | None = None, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    def _url(self, remote_id: str) -> str:
        return f"{self.base_url}/{quote(remote_id, safe='/')}"

    async def upload(self, remote_id: str, payload: bytes) -> None:
        response = await self._client.put(self._url(remote_id), content=payload, headers=self.headers)
        response.raise_for_status()

    async def download(self, remote_id: str) -> bytes:
        response = await self._client.get(self._url(remote_id), headers=self.headers)
        response.raise_for_status()
        return response.content

    async def close(self) -> None:
        await self._client.aclose()


class LocalNetworkStorageProvider:
    """Stores objects in a shared filesystem path, suitable for a mounted share."""

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).expanduser().resolve()

    def _path(self, remote_id: str) -> Path:
        candidate = (self.root_path / remote_id).resolve()
        if self.root_path != candidate and self.root_path not in candidate.parents:
            raise ValueError("Remote object ID escapes the configured storage path")
        return candidate

    async def upload(self, remote_id: str, payload: bytes) -> None:
        destination = self._path(remote_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(destination)

    async def download(self, remote_id: str) -> bytes:
        return self._path(remote_id).read_bytes()

    async def close(self) -> None:
        return None


class CloudSyncManager:
    """Synchronizes encrypted workflow checkpoints with revision-aware conflict detection."""

    _FORMAT_VERSION = 1
    _SALT_SIZE = 16
    _NONCE_SIZE = 12
    _KEY_SIZE = 32
    _ITERATIONS = 600_000
    _WORKFLOW_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    def __init__(self, recovery_engine: Any, database: AtrinDatabase | None = None,
                 storage_provider: StorageProvider | None = None):
        self.recovery_engine = recovery_engine
        self.database = database
        self.storage_provider = storage_provider
        self.sync_config: SyncConfig | None = None
        self._encryption_key: bytes | None = None

    async def close(self) -> None:
        provider = self.storage_provider
        close = getattr(provider, "close", None) if provider is not None else None
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result

    def configure_provider(self, provider_type: str, config: dict) -> SyncConfig:
        provider_type = provider_type.lower()
        if provider_type not in {"s3", "webdav", "local_network"}:
            raise ValueError("provider_type must be one of: s3, webdav, local_network")
        passphrase = config.get("encryption_key")
        if not isinstance(passphrase, str) or len(passphrase) < 12:
            raise ValueError("config.encryption_key must contain at least 12 characters")
        endpoint = config.get("endpoint_url")
        bucket = config.get("bucket_name")
        path = config.get("path")
        if provider_type in {"s3", "webdav"} and not isinstance(endpoint, str):
            raise ValueError("endpoint_url is required for HTTP storage providers")
        if provider_type == "s3" and not isinstance(bucket, str):
            raise ValueError("bucket_name is required for s3 storage")
        if provider_type == "local_network" and not (isinstance(path, str) or isinstance(endpoint, str)):
            raise ValueError("path or endpoint_url is required for local_network storage")

        salt_value = config.get("key_salt", "atrin-cloud-sync-v1")
        if not isinstance(salt_value, str):
            raise ValueError("config.key_salt must be a string")
        salt = salt_value.encode()
        self._encryption_key = self._derive_key(passphrase, salt)
        self.sync_config = SyncConfig(
            provider_type=provider_type,
            endpoint_url=endpoint if isinstance(endpoint, str) else None,
            bucket_name=bucket if isinstance(bucket, str) else None,
            path=path if isinstance(path, str) else None,
            encryption_key_hash=hashlib.sha256(passphrase.encode()).hexdigest(),
        )
        if provider_type == "local_network":
            local_path = path if isinstance(path, str) else self._file_url_path(endpoint if isinstance(endpoint, str) else None)
            self.storage_provider = LocalNetworkStorageProvider(local_path)
        else:
            assert isinstance(endpoint, str)
            base_url = endpoint.rstrip("/")
            if provider_type == "s3":
                assert isinstance(bucket, str)
                base_url = f"{base_url}/{quote(bucket, safe='')}"
            self.storage_provider = HTTPStorageProvider(base_url, dict(config.get("headers", {})))
        return self.sync_config

    def encrypt_payload(self, data: dict) -> bytes:
        key = self._require_key()
        salt = os.urandom(self._SALT_SIZE)
        nonce = os.urandom(self._NONCE_SIZE)
        derived_key = self._derive_key_from_key(key, salt)
        plaintext = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
        ciphertext = AESGCM(derived_key).encrypt(nonce, plaintext, None)
        return bytes([self._FORMAT_VERSION]) + salt + nonce + ciphertext

    def decrypt_payload(self, encrypted_data: bytes) -> dict:
        key = self._require_key()
        minimum_size = 1 + self._SALT_SIZE + self._NONCE_SIZE + 16
        if len(encrypted_data) < minimum_size or encrypted_data[0] != self._FORMAT_VERSION:
            raise ValueError("Unsupported or malformed encrypted checkpoint")
        offset = 1
        salt = encrypted_data[offset:offset + self._SALT_SIZE]
        offset += self._SALT_SIZE
        nonce = encrypted_data[offset:offset + self._NONCE_SIZE]
        ciphertext = encrypted_data[offset + self._NONCE_SIZE:]
        plaintext = AESGCM(self._derive_key_from_key(key, salt)).decrypt(nonce, ciphertext, None)
        value = json.loads(plaintext.decode())
        if not isinstance(value, dict):
            raise ValueError("Encrypted payload must contain a JSON object")
        return value

    @staticmethod
    def _canonical_checkpoint(checkpoint: dict) -> str:
        return json.dumps(checkpoint, separators=(",", ":"), sort_keys=True)

    @classmethod
    def _content_hash(cls, checkpoint: dict) -> str:
        return hashlib.sha256(cls._canonical_checkpoint(checkpoint).encode()).hexdigest()

    async def push_checkpoint(self, workflow_id: str) -> SyncStatus:
        provider = self._require_provider()
        checkpoint = await self._call(self.recovery_engine.checkpoint_store.load, workflow_id)
        if checkpoint is None:
            raise LookupError(f"No checkpoint found for workflow {workflow_id}")
        revision = int(checkpoint.get("revision", 0))
        content_hash = self._content_hash(checkpoint)
        synced_at = self._timestamp(checkpoint.get("updated_at"))
        envelope = {
            "checkpoint": checkpoint,
            "synced_at": synced_at,
            "revision": revision,
            "content_hash": content_hash,
            "format_version": self._FORMAT_VERSION,
        }
        remote_id = self._remote_id(workflow_id)
        await self._call(provider.upload, remote_id, self.encrypt_payload(envelope))
        self._write_metadata(workflow_id, remote_id, synced_at, SyncDirection.PUSH, False)
        return SyncStatus(last_synced_at=datetime.fromisoformat(synced_at), sync_direction=SyncDirection.PUSH,
                          remote_version=str(revision), local_version=str(revision))

    async def pull_checkpoint(self, workflow_id: str) -> dict:
        provider = self._require_provider()
        remote_id = self._remote_id(workflow_id)
        remote = self.decrypt_payload(await self._call(provider.download, remote_id))
        checkpoint = remote.get("checkpoint", remote)
        if not isinstance(checkpoint, dict):
            raise ValueError("Remote checkpoint payload is invalid")
        raw_remote_revision = remote.get("revision")
        if raw_remote_revision is None:
            raw_remote_revision = checkpoint.get("revision", 0)
        if not isinstance(raw_remote_revision, (int, float, str)):
            raise ValueError("Remote checkpoint revision is invalid")
        try:
            remote_revision = int(raw_remote_revision)
        except (TypeError, ValueError) as error:
            raise ValueError("Remote checkpoint revision is invalid") from error
        remote_hash = str(remote.get("content_hash") or self._content_hash(checkpoint))
        local = await self._call(self.recovery_engine.checkpoint_store.load, workflow_id)
        local_revision = int(local.get("revision", 0)) if isinstance(local, dict) else None
        local_hash = self._content_hash(local) if isinstance(local, dict) else None
        remote_timestamp = self._timestamp(remote.get("synced_at") or checkpoint.get("updated_at"))

        if local is None:
            conflict = False
        else:
            assert local_revision is not None
            assert local_hash is not None
            conflict = remote_revision != local_revision or remote_hash != local_hash

        self._write_metadata(
            workflow_id, remote_id, remote_timestamp,
            SyncDirection.CONFLICT if conflict else SyncDirection.PULL, conflict,
        )
        if conflict:
            return {
                "checkpoint": checkpoint,
                "conflict": True,
                "local_revision": local_revision,
                "remote_revision": remote_revision,
                "local_hash": local_hash,
                "remote_hash": remote_hash,
                "warning": "Local and remote checkpoints diverged; review before applying.",
            }
        return checkpoint

    def _require_key(self) -> bytes:
        if self._encryption_key is None:
            raise RuntimeError("Configure a sync provider before encrypting payloads")
        return self._encryption_key

    def _require_provider(self) -> StorageProvider:
        if self.sync_config is None or self.storage_provider is None:
            raise RuntimeError("Configure a sync provider before syncing checkpoints")
        return self.storage_provider

    def _remote_id(self, workflow_id: str) -> str:
        if not self._WORKFLOW_ID.fullmatch(workflow_id):
            raise ValueError("workflow_id contains unsupported path characters")
        config = self.sync_config
        prefix = config.path.strip("/") if config and config.path else "checkpoints"
        return f"{prefix}/{workflow_id}.checkpoint"

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes) -> bytes:
        return PBKDF2HMAC(algorithm=SHA256(), length=CloudSyncManager._KEY_SIZE, salt=salt,
                          iterations=CloudSyncManager._ITERATIONS).derive(passphrase.encode())

    @classmethod
    def _derive_key_from_key(cls, key: bytes, salt: bytes) -> bytes:
        return PBKDF2HMAC(algorithm=SHA256(), length=cls._KEY_SIZE, salt=salt,
                          iterations=cls._ITERATIONS).derive(key)

    @staticmethod
    def _timestamp(value: Any) -> str:
        if isinstance(value, datetime):
            parsed = value
        elif value:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        else:
            parsed = datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _file_url_path(value: str | None) -> str:
        parsed = urlparse(value or "")
        return parsed.path if parsed.scheme == "file" else (value or "")

    def _write_metadata(self, workflow_id: str, remote_id: str, timestamp: str,
                        direction: SyncDirection, conflict: bool) -> None:
        if self.database is None:
            return
        connection = self.database.get_connection()
        try:
            connection.execute("""INSERT INTO sync_metadata
                (workflow_id, remote_id, last_synced_at, sync_status, conflict_flag)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET remote_id=excluded.remote_id,
                last_synced_at=excluded.last_synced_at, sync_status=excluded.sync_status,
                conflict_flag=excluded.conflict_flag""",
                (workflow_id, remote_id, timestamp, direction.value, int(conflict)))
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    async def _call(method: Any, *args: Any) -> Any:
        result = method(*args)
        return await result if inspect.isawaitable(result) else result
