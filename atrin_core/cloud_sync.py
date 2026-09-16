"""Encrypted, vendor-neutral checkpoint synchronization."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
import uuid
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


class RemoteRevisionConflictError(RuntimeError):
    """
    FIX (بند ۹/۲۱): raised by push_checkpoint() when the remote checkpoint has
    advanced past what this client last observed — protects against a blind
    overwrite when two clients push concurrently.
    """

    def __init__(self, workflow_id: str, local_revision: int, remote_revision: "int | None"):
        self.workflow_id = workflow_id
        self.local_revision = local_revision
        self.remote_revision = remote_revision
        if remote_revision is None:
            detail = (
                "a concurrent write was detected by the atomic compare-and-swap layer "
                "(exact remote revision not re-read)"
            )
        else:
            detail = f"is at revision {remote_revision}, ahead of the last known revision"
        super().__init__(
            f"Remote checkpoint for workflow {workflow_id} {detail} "
            f"(pushing revision {local_revision}); pull and resolve before pushing again"
        )


class RemoteObjectNotFoundError(LookupError):
    """
    Raised by a StorageProvider.download() implementation to signal
    specifically 'this object does not exist yet' — as opposed to a
    network timeout, auth failure, TLS error, or any other transient
    condition. push_checkpoint()'s conflict check treats ONLY this case
    as safe to proceed with a first push; every other exception is
    treated as 'remote state unknown' and blocks the push.
    """


class RemoteStateUnknownError(RuntimeError):
    """
    FIX: raised by push_checkpoint() when the remote's current state
    could not be confirmed (network timeout, DNS failure, 401/403, TLS
    error, or corrupted/undecryptable remote payload) — as opposed to a
    confirmed 'object does not exist' (RemoteObjectNotFoundError), which
    is the only case safe to treat as a first push. Previously ANY
    exception during the pre-push existence check was silently treated
    as 'no prior object, proceed' — meaning a transient network blip
    could bypass the entire compare-and-swap protection and overwrite a
    remote checkpoint the client never actually verified.
    """

    def __init__(self, workflow_id: str, underlying: BaseException):
        self.workflow_id = workflow_id
        self.underlying = underlying
        super().__init__(
            f"Cannot confirm remote state for workflow {workflow_id} before push "
            f"({type(underlying).__name__}: {underlying}); refusing to push without "
            f"a confirmed baseline. Retry once connectivity/auth/decryption is restored, "
            f"or pass force=True to override."
        )


class StorageProvider(Protocol):
    async def upload(self, remote_id: str, payload: bytes) -> None: ...
    async def download(self, remote_id: str) -> bytes: ...
    # FIX: capability flag so push_checkpoint() can tell whether a provider
    # offers a TRUE atomic compare-and-swap (an optional upload_if_unchanged
    # method some providers implement) or only the weaker read-check-write
    # pattern. Not every StorageProvider implements upload_if_unchanged —
    # it's accessed dynamically (getattr) only when this flag is True — so
    # it's intentionally NOT part of this Protocol's structural contract.
    supports_atomic_cas: bool = False


class HTTPStorageProvider:
    """
    Uses standard HTTP PUT/GET for S3-compatible and WebDAV endpoints.

    supports_atomic_cas is honestly False here: we cannot assume an
    arbitrary configured endpoint supports conditional PUT (If-Match /
    If-None-Match) or versioned objects. push_checkpoint() falls back to
    its optimistic pre-flight conflict *detection* for this provider —
    which narrows the race window but is NOT a true atomic CAS.
    """

    supports_atomic_cas = False

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
        if response.status_code == 404:
            raise RemoteObjectNotFoundError(f"No remote object at {remote_id!r}")
        response.raise_for_status()
        return response.content

    async def close(self) -> None:
        await self._client.aclose()


class LocalNetworkStorageProvider:
    """
    Stores objects in a shared filesystem path, suitable for a mounted share.

    Unlike HTTPStorageProvider, this backend is fully under our control, so
    it implements a REAL atomic compare-and-swap via an exclusive lock file
    (O_CREAT | O_EXCL) around the check-then-write sequence — closing the
    TOCTOU gap that the plain read-check-write pattern has. Two clients
    sharing the same mounted path will genuinely serialize through the
    lock, not just detect a conflict after the fact.
    """

    supports_atomic_cas = True

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).expanduser().resolve()

    def _path(self, remote_id: str) -> Path:
        candidate = (self.root_path / remote_id).resolve()
        if self.root_path != candidate and self.root_path not in candidate.parents:
            raise ValueError("Remote object ID escapes the configured storage path")
        return candidate

    def _lock_path(self, remote_id: str) -> Path:
        return self._path(remote_id).with_name(self._path(remote_id).name + ".lock")

    async def _acquire_lock(self, lock_path: Path, *, timeout: float = 10.0, stale_after: float = 30.0) -> None:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        while True:
            try:
                descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, str(os.getpid()).encode("utf-8"))
                os.close(descriptor)
                return
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue  # lock was released between our open() and stat()
                if age > stale_after:
                    # A crashed holder left this behind — reclaim it rather
                    # than deadlock forever.
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Could not acquire sync lock for {lock_path} within {timeout}s"
                    ) from None
                await asyncio.sleep(0.05)

    def _release_lock(self, lock_path: Path) -> None:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass

    async def upload_if_unchanged(
        self, remote_id: str, payload: bytes, *, expected_remote_hash: str | None
    ) -> bool:
        """
        TRUE atomic compare-and-swap: acquire an exclusive lock, verify the
        object's current content hash still matches expected_remote_hash
        (None means 'caller believes no object exists yet'), and only then
        perform the atomic-rename write — all while holding the lock, so no
        other process sharing this path can interleave between the check
        and the write. Returns False (without writing) on a mismatch.
        """
        destination = self._path(remote_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._lock_path(remote_id)
        await self._acquire_lock(lock_path)
        try:
            current_hash: str | None = None
            if destination.exists():
                current_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
            if current_hash != expected_remote_hash:
                return False
            temporary = destination.with_name(destination.name + f".tmp.{uuid.uuid4().hex}")
            temporary.write_bytes(payload)
            temporary.replace(destination)
            return True
        finally:
            self._release_lock(lock_path)

    async def upload(self, remote_id: str, payload: bytes) -> None:
        """Unconditional overwrite (used for force=True). Still lock-serialized
        against concurrent upload_if_unchanged() callers to avoid corrupting
        their check-then-write window."""
        destination = self._path(remote_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._lock_path(remote_id)
        await self._acquire_lock(lock_path)
        try:
            temporary = destination.with_name(destination.name + f".tmp.{uuid.uuid4().hex}")
            temporary.write_bytes(payload)
            temporary.replace(destination)
        finally:
            self._release_lock(lock_path)

    async def download(self, remote_id: str) -> bytes:
        try:
            return self._path(remote_id).read_bytes()
        except FileNotFoundError as error:
            raise RemoteObjectNotFoundError(f"No remote object at {remote_id!r}") from error

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
            encryption_key_hash=hashlib.sha256(self._encryption_key).hexdigest(),
        )
        if provider_type == "local_network":
            local_path = path if isinstance(path, str) else self._file_url_path(endpoint if isinstance(endpoint, str) else None)
            self.storage_provider = LocalNetworkStorageProvider(local_path)
        else:
            if not isinstance(endpoint, str):
                raise ValueError("endpoint_url is required for HTTP storage providers")
            base_url = endpoint.rstrip("/")
            if provider_type == "s3":
                if not isinstance(bucket, str):
                    raise ValueError("bucket_name is required for s3 storage")
                base_url = f"{base_url}/{quote(bucket, safe='')}"
            headers = config.get("headers", {})
            if not isinstance(headers, dict):
                raise ValueError("config.headers must be an object")
            self.storage_provider = HTTPStorageProvider(base_url, {str(k): str(v) for k, v in headers.items()})
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

    async def push_checkpoint(self, workflow_id: str, *, force: bool = False) -> SyncStatus:
        """
        Compare-and-swap guard before overwriting the remote checkpoint.

        For providers with supports_atomic_cas=True (LocalNetworkStorageProvider),
        this performs a REAL atomic compare-and-swap: the existence/content
        check and the write happen under a single exclusive lock, so no
        other client sharing that path can interleave between them.

        For providers without atomic support (HTTPStorageProvider — we
        cannot assume an arbitrary configured endpoint supports conditional
        PUT / ETag headers), this falls back to a client-side pre-flight
        check: compare the remote's *current* revision against the revision
        this client last observed. This narrows the race window
        considerably but is NOT a true atomic CAS — a write from another
        client landing in the brief gap between our check and our own
        upload() is still possible. Prefer a supports_atomic_cas=True
        provider when true consistency guarantees matter.

        Either way, if the remote has moved on since our last pull/push,
        the overwrite is refused with RemoteRevisionConflictError instead
        of silently clobbering it. Pass force=True to intentionally
        overwrite anyway (e.g. after the caller has resolved the conflict
        via pull_checkpoint()).
        """
        provider = self._require_provider()
        checkpoint = await self._call(self.recovery_engine.checkpoint_store.load, workflow_id)
        if checkpoint is None:
            raise LookupError(f"No checkpoint found for workflow {workflow_id}")
        revision = int(checkpoint.get("revision", 0))
        content_hash = self._content_hash(checkpoint)
        synced_at = self._timestamp(checkpoint.get("updated_at"))
        remote_id = self._remote_id(workflow_id)

        envelope = {
            "checkpoint": checkpoint,
            "synced_at": synced_at,
            "revision": revision,
            "content_hash": content_hash,
            "format_version": self._FORMAT_VERSION,
        }
        encrypted_payload = self.encrypt_payload(envelope)

        atomic_cas = bool(getattr(provider, "supports_atomic_cas", False))
        expected_remote_hash: str | None = None

        if not force:
            last_known = self._read_last_known_remote_revision(workflow_id)
            try:
                raw_existing = await self._call(provider.download, remote_id)
                existing = self.decrypt_payload(raw_existing)
                remote_revision = int(existing.get("revision", 0))
                expected_remote_hash = hashlib.sha256(raw_existing).hexdigest()
            except RemoteObjectNotFoundError:
                # FIX: confirmed absence — genuinely safe to treat as a first push.
                remote_revision = None
                expected_remote_hash = None
            except Exception as error:
                # FIX: anything else (network timeout, DNS failure, 401/403,
                # TLS error, corrupted/undecryptable payload) means we could
                # NOT confirm the remote's actual state. Previously this was
                # conflated with "object doesn't exist" and silently allowed
                # the push to proceed — defeating the whole point of the CAS
                # check. Refuse instead; the caller can retry or pass
                # force=True once they've deliberately decided to override.
                raise RemoteStateUnknownError(workflow_id, error) from error
            if remote_revision is not None and (last_known is None or remote_revision > last_known):
                # Someone else advanced the remote past what we last saw.
                if remote_revision >= revision:
                    raise RemoteRevisionConflictError(
                        workflow_id=workflow_id,
                        local_revision=revision,
                        remote_revision=remote_revision,
                    )

        if not force and atomic_cas:
            # FIX: real atomic CAS path — the existence/hash check above was
            # only our best guess at the time we made it. The lock-protected
            # write below re-verifies under mutual exclusion and PROVES
            # whether a concurrent writer landed in between, instead of
            # just narrowing the probability.
            # (upload_if_unchanged is not part of the StorageProvider Protocol's
            # structural contract — only providers with supports_atomic_cas=True
            # implement it, checked dynamically via the guard above.)
            written = await provider.upload_if_unchanged(  # type: ignore[attr-defined]
                remote_id, encrypted_payload, expected_remote_hash=expected_remote_hash
            )
            if not written:
                raise RemoteRevisionConflictError(
                    workflow_id=workflow_id,
                    local_revision=revision,
                    remote_revision=None,  # proven by the atomic layer, exact value not re-read
                )
        else:
            await self._call(provider.upload, remote_id, encrypted_payload)

        self._write_metadata(workflow_id, remote_id, synced_at, SyncDirection.PUSH, False,
                              known_remote_revision=revision)
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
            if local_revision is None or local_hash is None:
                raise ValueError("Local checkpoint metadata is incomplete")
            conflict = remote_revision != local_revision or remote_hash != local_hash

        # FIX (بند ۹/۲۱): record the remote revision we just observed so a
        # subsequent push_checkpoint() has an up-to-date baseline for its
        # conflict check, even when this pull itself detected a conflict.
        self._write_metadata(
            workflow_id, remote_id, remote_timestamp,
            SyncDirection.CONFLICT if conflict else SyncDirection.PULL, conflict,
            known_remote_revision=remote_revision,
        )
        if conflict:
            return {
                "checkpoint": checkpoint,
                "conflict": True,
                "local_revision": local_revision,
                "remote_revision": remote_revision,
                "local_hash": local_hash,
                "remote_hash": remote_hash,
                "local_timestamp": local.get("updated_at") if isinstance(local, dict) else None,
                "remote_timestamp": remote.get("synced_at") or checkpoint.get("updated_at"),
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
                        direction: SyncDirection, conflict: bool,
                        known_remote_revision: int | None = None) -> None:
        if self.database is None:
            return
        connection = self.database.get_connection()
        try:
            if known_remote_revision is None:
                connection.execute("""INSERT INTO sync_metadata
                    (workflow_id, remote_id, last_synced_at, sync_status, conflict_flag)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET remote_id=excluded.remote_id,
                    last_synced_at=excluded.last_synced_at, sync_status=excluded.sync_status,
                    conflict_flag=excluded.conflict_flag""",
                    (workflow_id, remote_id, timestamp, direction.value, int(conflict)))
            else:
                # FIX (بند ۹/۲۱): also persist the revision we just observed
                # on the remote, so the next push_checkpoint() can detect a
                # concurrent write by comparing against this value.
                connection.execute("""INSERT INTO sync_metadata
                    (workflow_id, remote_id, last_synced_at, sync_status, conflict_flag, last_known_remote_revision)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET remote_id=excluded.remote_id,
                    last_synced_at=excluded.last_synced_at, sync_status=excluded.sync_status,
                    conflict_flag=excluded.conflict_flag,
                    last_known_remote_revision=excluded.last_known_remote_revision""",
                    (workflow_id, remote_id, timestamp, direction.value, int(conflict), known_remote_revision))
            connection.commit()
        finally:
            connection.close()

    def _read_last_known_remote_revision(self, workflow_id: str) -> int | None:
        if self.database is None:
            return None
        connection = self.database.get_connection()
        try:
            row = connection.execute(
                "SELECT last_known_remote_revision FROM sync_metadata WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            if row is None or row["last_known_remote_revision"] is None:
                return None
            return int(row["last_known_remote_revision"])
        finally:
            connection.close()

    @staticmethod
    async def _call(method: Any, *args: Any) -> Any:
        result = method(*args)
        return await result if inspect.isawaitable(result) else result
