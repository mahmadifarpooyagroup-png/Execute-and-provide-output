from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import os
import secrets
from pathlib import Path
from typing import Optional


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


class LocalSecurityManager:
    """Manage the local runtime token with platform-aware at-rest protection."""

    def __init__(self, token_file_path: str = ".atrin_data/runtime_secret.token"):
        self.token_file_path = token_file_path
        self._token: Optional[str] = None

    @staticmethod
    def _windows_protect(value: bytes) -> bytes:
        if os.name != "nt":
            return value
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        source = ctypes.create_string_buffer(value)
        in_blob = _DATA_BLOB(len(value), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
        out_blob = _DATA_BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    @staticmethod
    def _windows_unprotect(value: bytes) -> bytes:
        if os.name != "nt":
            return value
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        source = ctypes.create_string_buffer(value)
        in_blob = _DATA_BLOB(len(value), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
        out_blob = _DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    @staticmethod
    def _is_valid_token(value: str) -> bool:
        return len(value) >= 32 and "\x00" not in value and "\n" not in value and "\r" not in value

    def _encode_for_storage(self, token: str) -> bytes:
        return base64.b64encode(self._windows_protect(token.encode("utf-8")))

    def _write_token(self, token: str) -> None:
        token_path = Path(self.token_file_path).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = token_path.with_name(token_path.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, self._encode_for_storage(token))
        finally:
            os.close(descriptor)
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, token_path)

    def _read_token(self, token_path: Path) -> str:
        stored = token_path.read_bytes()

        # Preferred format: base64-wrapped protected bytes.
        try:
            protected = base64.b64decode(stored, validate=True)
            raw = self._windows_unprotect(protected)
            token = raw.decode("utf-8").strip()
            if self._is_valid_token(token):
                return token
        except Exception:
            pass

        # Legacy format: plaintext token written by older Atrin versions.
        try:
            legacy = stored.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise RuntimeError("Stored runtime token is corrupted") from error
        if not self._is_valid_token(legacy):
            raise RuntimeError("Stored runtime token is invalid or corrupted")

        # Upgrade in place so an existing installation continues working while
        # immediately moving to the new protected storage format.
        self._write_token(legacy)
        return legacy

    def get_or_create_token(self) -> str:
        if self._token:
            return self._token
        token_path = Path(self.token_file_path).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        if token_path.is_symlink():
            raise RuntimeError("Token path must not be a symbolic link")
        try:
            self._token = self._read_token(token_path)
            if os.name != "nt":
                os.chmod(token_path, 0o600)
        except FileNotFoundError:
            token = secrets.token_urlsafe(32)
            self._write_token(token)
            self._token = token
        return self._token

    def validate_token(self, provided_token: str) -> bool:
        if not isinstance(provided_token, str) or not self._is_valid_token(provided_token):
            return False
        try:
            return secrets.compare_digest(provided_token, self.get_or_create_token())
        except RuntimeError:
            return False
