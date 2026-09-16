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


def test_tauri_raw_file_read_now_validates(tmp_path):
    """
    Regression guard for the Tauri <-> Python token contract mismatch.

    frontend/src-tauri/src/lib.rs::runtime_is_owned() reads the token file
    with a plain std::fs::read_to_string() and forwards those raw bytes
    verbatim as the X-Atrin-Token header — it does not decode the
    at-rest-protected (base64, and on Windows also DPAPI-wrapped) format
    _write_token() persists. Before this fix, validate_token() only ever
    accepted the *decoded* plaintext, so a packaged Tauri app could never
    successfully authenticate against its own bundled Python runtime.
    """
    path = str(tmp_path / "runtime.token")
    manager = LocalSecurityManager(path)
    plaintext = manager.get_or_create_token()

    with open(path, "r", encoding="utf-8") as handle:
        raw_on_disk_content = handle.read().strip()

    # The on-disk representation must differ from the plaintext (proves
    # this test actually exercises the encode/decode gap, not a no-op).
    assert raw_on_disk_content != plaintext

    # Both representations must now validate successfully.
    assert manager.validate_token(plaintext) is True
    assert manager.validate_token(raw_on_disk_content) is True


def test_arbitrary_wrong_value_is_still_rejected(tmp_path):
    """Accepting the on-disk representation must not weaken rejection of unrelated strings."""
    path = str(tmp_path / "runtime.token")
    manager = LocalSecurityManager(path)
    manager.get_or_create_token()

    assert manager.validate_token("") is False
    assert manager.validate_token("completely-unrelated-value") is False
    assert manager.validate_token("A" * 5000) is False  # oversized input rejected


def test_legacy_plaintext_file_content_matches_both_representations(tmp_path):
    """
    For a legacy plaintext token file (pre-migration format), the raw
    on-disk bytes and the decoded plaintext happen to be identical before
    _write_token() re-encodes it — both forms must still validate.
    """
    path = tmp_path / "legacy.token"
    legacy = "B" * 48
    path.write_text(legacy, encoding="utf-8")
    manager = LocalSecurityManager(str(path))

    assert manager.validate_token(legacy) is True

    # After the first get_or_create_token() call, the file has been
    # re-written in the protected format — the NEW on-disk bytes must
    # also validate (this is the Rust-facing contract going forward).
    with open(path, "r", encoding="utf-8") as handle:
        new_raw_content = handle.read().strip()
    assert manager.validate_token(new_raw_content) is True
