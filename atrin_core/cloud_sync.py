"""Encrypted, vendor-neutral checkpoint synchronization."""

import hashlib
import inspect
import json
import os
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

    def __init__(self, base_url: str, headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}

    def _url(self, remote_id: str) -> str:
        return f"{self.base_url}/{quote(remote_id, safe='/')}"

    async def upload(self, remote_id: str, payload: bytes) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.put(self._url(remote_id), content=payload, headers=self.headers)
            response.raise_for_status()

    async def download(self, remote_id: str) -> bytes:
        async with httpx.AsyncClient() as client:
            response = await client.get(self._url(remote_id), headers=self.headers)
            response.raise_for_status()
            return response.content


class LocalNetworkStorageProvider:
    """Stores objects in a shared filesystem path, suitable for a mounted share."""

    def __init__(self, root_path: str):
        self.root_path = Path(root_path)

    def _path(self, remote_id: str) -> Path:
        candidate = (self.root_path / remote_id).resolve()
        root = self.root_path.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError("Remote object ID escapes the configured storage path")
        return candidate

    async def upload(self, remote_id: str, payload: bytes) -> None:
        destination = self._path(remote_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    async def download(self, remote_id: str) -> bytes:
        return self._path(remote_id).read_bytes()


class CloudSyncManager:
    """Synchronizes encrypted workflow checkpoints through a configured provider."""

    _FORMAT_VERSION = 1
    _SALT_SIZE = 16
    _NONCE_SIZE = 12
    _KEY_SIZE = 32
    _ITERATIONS = 600_000

    def __init__(
        self,
        recovery_engine: Any,
        database: AtrinDatabase | None = None,
        storage_provider: StorageProvider | None = None,
    ):
        self.recovery_engine = recovery_engine
        self.database = database
        self.storage_provider = storage_provider
        self.sync_config: SyncConfig | None = None
        self._encryption_key: bytes | None = None

    def configure_provider(self, provider_type: str, config: dict) -> SyncConfig:
        provider_type = provider_type.lower()
        if provider_type not in {"s3", "webdav", "local_network"}:
            raise ValueError("provider_type must be one of: s3, webdav, local_network")

        passphrase = config.get("encryption_key")
        if not isinstance(passphrase, str) or not passphrase:
            raise ValueError("config.encryption_key must be a non-empty user-derived secret")
        endpoint = config.get("endpoint_url")
        bucket = config.get("bucket_name")
        path = config.get("path")
        if provider_type in {"s3", "webdav"} and not endpoint:
            raise ValueError("endpoint_url is required for HTTP storage providers")
        if provider_type == "s3" and not bucket:
            raise ValueError("bucket_name is required for s3 storage")
        if provider_type == "local_network" and not (path or endpoint):
            raise ValueError("path or endpoint_url is required for local_network storage")

        salt = config.get("key_salt", "atrin-cloud-sync-v1").encode()
        self._encryption_key = self._derive_key(passphrase, salt)
        self.sync_config = SyncConfig(
            provider_type=provider_type,
            endpoint_url=endpoint,
            bucket_name=bucket,
            path=path,
            encryption_key_hash=hashlib.sha256(passphrase.encode()).hexdigest(),
        )
        if provider_type == "local_network":
            root = path or self._file_url_path(endpoint)
            self.storage_provider = LocalNetworkStorageProvider(root)
        else:
            base_url = endpoint.rstrip("/")
            if provider_type == "s3":
                base_url = f"{base_url}/{quote(bucket, safe='')}"
            headers = dict(config.get("headers", {}))
            self.storage_provider = HTTPStorageProvider(base_url, headers)
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

    async def push_checkpoint(self, workflow_id: str) -> SyncStatus:
        self._require_provider()
        checkpoint = await self._call(self.recovery_engine.checkpoint_store.load, workflow_id)
        if checkpoint is None:
            raise LookupError(f"No checkpoint found for workflow {workflow_id}")
        timestamp = self._timestamp(checkpoint.get("updated_at"))
        envelope = {"checkpoint": checkpoint, "synced_at": timestamp, "version": self._version(checkpoint)}
        remote_id = self._remote_id(workflow_id)
        await self._call(self.storage_provider.upload, remote_id, self.encrypt_payload(envelope))
        self._write_metadata(workflow_id, remote_id, timestamp, SyncDirection.PUSH, False)
        return SyncStatus(last_synced_at=datetime.fromisoformat(timestamp), sync_direction=SyncDirection.PUSH,
                          remote_version=envelope["version"], local_version=envelope["version"])

    async def pull_checkpoint(self, workflow_id: str) -> dict:
        self._require_provider()
        remote_id = self._remote_id(workflow_id)
        remote = self.decrypt_payload(await self._call(self.storage_provider.download, remote_id))
        checkpoint = remote.get("checkpoint", remote)
        local = await self._call(self.recovery_engine.checkpoint_store.load, workflow_id)
        remote_timestamp = self._timestamp(remote.get("synced_at") or checkpoint.get("updated_at"))
        local_timestamp = self._timestamp(local.get("updated_at")) if local else None
        conflict = bool(local and local_timestamp and remote_timestamp > local_timestamp)
        self._write_metadata(workflow_id, remote_id, remote_timestamp, SyncDirection.CONFLICT if conflict else SyncDirection.PULL, conflict)
        if conflict:
            return {"checkpoint": checkpoint, "conflict": True, "local_timestamp": local_timestamp,
                    "remote_timestamp": remote_timestamp, "warning": "Remote checkpoint is newer; review before applying."}
        return checkpoint

    def _require_key(self) -> bytes:
        if self._encryption_key is None:
            raise RuntimeError("Configure a sync provider before encrypting payloads")
        return self._encryption_key

    def _require_provider(self) -> None:
        if self.sync_config is None or self.storage_provider is None:
            raise RuntimeError("Configure a sync provider before syncing checkpoints")

    def _remote_id(self, workflow_id: str) -> str:
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
    def _version(checkpoint: dict) -> str:
        return str(checkpoint.get("checkpoint_version", checkpoint.get("updated_at", "1")))

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
