from __future__ import annotations

from datetime import datetime, timezone

from .database import AtrinDatabase
from .models import AuthState


class SessionManager:
    """Manage durable provider sessions and exclusive workflow ownership."""

    _LEASE_SECONDS = 300

    def __init__(self, db: AtrinDatabase):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS provider_profiles (
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    auth_state TEXT DEFAULT 'UNKNOWN',
                    fencing_token INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    provider_profile_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    state TEXT DEFAULT 'UNKNOWN',
                    lock_owner TEXT,
                    lease_expiry REAL,
                    fencing_token INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (provider_profile_id) REFERENCES provider_profiles(id)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def create_profile(self, profile_id: str, provider_id: str, account_id: str, name: str) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO provider_profiles "
                "(id, provider_id, account_id, name, auth_state, fencing_token) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (profile_id, provider_id, account_id, name, AuthState.UNKNOWN.value, 0),
            )
            conn.commit()
        finally:
            conn.close()

    def acquire_lock(self, profile_id: str, workflow_id: str) -> int:
        """Acquire or renew a profile lease.

        The same live owner keeps its fencing generation. A takeover is allowed
        only after the previous lease expires, at which point the fencing token
        is advanced so stale workers are rejected.
        """
        now_ts = datetime.now(timezone.utc).timestamp()
        new_expiry = now_ts + self._LEASE_SECONDS
        conn = self.db.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            profile = conn.execute(
                "SELECT account_id, fencing_token FROM provider_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
            if profile is None:
                raise LookupError(f"Provider profile is not registered: {profile_id}")

            session = conn.execute(
                "SELECT lock_owner, lease_expiry, fencing_token FROM sessions WHERE session_id = ?",
                (profile_id,),
            ).fetchone()
            if session:
                owner = session["lock_owner"]
                expiry = float(session["lease_expiry"] or 0)
                if owner == workflow_id and expiry > now_ts:
                    conn.execute(
                        "UPDATE sessions SET lease_expiry=?, updated_at=CURRENT_TIMESTAMP "
                        "WHERE session_id=? AND lock_owner=? AND fencing_token=?",
                        (new_expiry, profile_id, workflow_id, session["fencing_token"]),
                    )
                    conn.commit()
                    return int(session["fencing_token"])
                if owner not in (None, workflow_id) and expiry > now_ts:
                    raise RuntimeError(f"Provider profile is locked by workflow: {owner}")

            new_token = int(profile["fencing_token"]) + 1
            conn.execute(
                "UPDATE provider_profiles SET fencing_token=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_token, profile_id),
            )
            conn.execute(
                "INSERT INTO sessions "
                "(session_id, provider_profile_id, account_id, state, lock_owner, lease_expiry, fencing_token, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "account_id=excluded.account_id, lock_owner=excluded.lock_owner, "
                "lease_expiry=excluded.lease_expiry, fencing_token=excluded.fencing_token, "
                "updated_at=CURRENT_TIMESTAMP",
                (
                    profile_id,
                    profile_id,
                    profile["account_id"],
                    AuthState.UNKNOWN.value,
                    workflow_id,
                    new_expiry,
                    new_token,
                ),
            )
            conn.commit()
            return new_token
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def renew_lock(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        expiry = datetime.now(timezone.utc).timestamp() + self._LEASE_SECONDS
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                "UPDATE sessions SET lease_expiry=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE session_id=? AND lock_owner=? AND fencing_token=? AND lease_expiry>?",
                (expiry, profile_id, workflow_id, fencing_token, datetime.now(timezone.utc).timestamp()),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def release_lock(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                "UPDATE sessions SET lock_owner=NULL, lease_expiry=NULL, updated_at=CURRENT_TIMESTAMP "
                "WHERE session_id=? AND lock_owner=? AND fencing_token=?",
                (profile_id, workflow_id, fencing_token),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def validate_execution_lease(
        self,
        profile_id: str,
        workflow_id: str,
        fencing_token: int,
    ) -> bool:
        """Validate owner, exact fence and non-expired lease atomically enough for execution admission."""
        now_ts = datetime.now(timezone.utc).timestamp()
        connection = self.db.get_connection()
        try:
            row = connection.execute(
                "SELECT lock_owner, lease_expiry, fencing_token "
                "FROM sessions WHERE session_id=?",
                (profile_id,),
            ).fetchone()
            if row is None:
                return False
            return (
                row["lock_owner"] == workflow_id
                and float(row["lease_expiry"] or 0) > now_ts
                and int(row["fencing_token"]) == int(fencing_token)
            )
        finally:
            connection.close()

    def validate_fencing_token(self, profile_id: str, fencing_token: int) -> bool:
        """Backward-compatible exact fence check."""
        connection = self.db.get_connection()
        try:
            row = connection.execute(
                "SELECT fencing_token FROM provider_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            return row is not None and int(row[0]) == int(fencing_token)
        finally:
            connection.close()

    def get_session_state(self, profile_id: str) -> str:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT auth_state FROM provider_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            return row[0] if row else AuthState.UNKNOWN.value
        finally:
            conn.close()
