import secrets
import os
from typing import Optional

class LocalSecurityManager:
    def __init__(self, token_file_path: str = ".atrin_data/runtime_secret.token"):
        self.token_file_path = token_file_path
        self._token: Optional[str] = None

    def get_or_create_token(self) -> str:
        if self._token:
            return self._token
        
        os.makedirs(os.path.dirname(os.path.abspath(self.token_file_path)), exist_ok=True)
        
        if os.path.exists(self.token_file_path):
            with open(self.token_file_path, "r") as f:
                self._token = f.read().strip()
        else:
            self._token = secrets.token_urlsafe(32)
            with open(self.token_file_path, "w") as f:
                f.write(self._token)
            os.chmod(self.token_file_path, 0o600) # بخش ۴۳: محافظت از فایل راز
            
        return self._token

    def validate_token(self, provided_token: str) -> bool:
        return secrets.compare_digest(provided_token, self.get_or_create_token())
