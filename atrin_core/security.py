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

    def _write_token(self, token: str) -> None:
        token_path = Path(self.token_file_path).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        raw = token.encode("utf-8")
        protected = self._windows_protect(raw)
        encoded = base64.b64encode(protected)
        descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)
        if os.name != "nt":
            os.chmod(token_path, 0o600)

    def _read_token(self, token_path: Path) -> str:
        encoded = token_path.read_bytes()
        try:
            protected = base64.b64decode(encoded, validate=True)
            raw = self._windows_unprotect(protected)
        except Exception as error:
            raise RuntimeError("Stored runtime token cannot be decrypted or is corrupted") from error
        token = raw.decode("utf-8").strip()
        if len(token) < 32:
            raise RuntimeError("Stored token is invalid")
        return token

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
        if not isinstance(provided_token, str) or len(provided_token) < 32:
            return False
        try:
            return secrets.compare_digest(provided_token, self.get_or_create_token())
        except RuntimeError:
            return False
