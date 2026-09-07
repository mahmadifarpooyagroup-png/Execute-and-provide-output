import os

from atrin_core.security import LocalSecurityManager


def test_runtime_token_creation_and_validation(tmp_path):
    path = str(tmp_path / "runtime.token")
    manager = LocalSecurityManager(path)
    token = manager.get_or_create_token()
    assert len(token) >= 32
    assert manager.validate_token(token) is True
    assert manager.validate_token("wrong") is False
    assert manager.get_or_create_token() == token


def test_legacy_plaintext_token_is_migrated(tmp_path):
    path = tmp_path / "legacy.token"
    legacy = "A" * 48
    path.write_text(legacy, encoding="utf-8")
    manager = LocalSecurityManager(str(path))
    assert manager.get_or_create_token() == legacy
    assert manager.validate_token(legacy) is True
    stored = path.read_bytes()
    assert stored != legacy.encode("utf-8")
    if os.name != "nt":
        assert os.stat(path).st_mode & 0o077 == 0
