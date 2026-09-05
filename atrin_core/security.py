import secrets
import os
from pathlib import Path
from typing import Optional

class LocalSecurityManager:
    def __init__(self, token_file_path: str = ".atrin_data/runtime_secret.token"):
        self.token_file_path = token_file_path
        self._token: Optional[str] = None

    def get_or_create_token(self) -> str:
        if self._token:
            return self._token

        token_path = Path(self.token_file_path).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if token_path.is_symlink():
                raise RuntimeError("Token path must not be a symbolic link")
            self._token = token_path.read_text(encoding="utf-8").strip()
            if len(self._token) < 32:
                raise RuntimeError("Stored token is invalid")
            os.chmod(token_path, 0o600)
        except FileNotFoundError:
            token = secrets.token_urlsafe(32)
            descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(descriptor, token.encode("utf-8"))
            finally:
                os.close(descriptor)
            self._token = token

        return self._token

    def validate_token(self, provided_token: str) -> bool:
        if not isinstance(provided_token, str):
            return False
        return secrets.compare_digest(provided_token, self.get_or_create_token())
