from datetime import datetime, timezone, timedelta

from .database import AtrinDatabase
from .models import AuthState


class SessionManager:
    """Manage durable provider sessions and exclusive workflow ownership."""

    _LEASE_SECONDS = 300

    def __init__(self, db: AtrinDatabase):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self):
        conn = self.db.get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_profiles (
                id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                name TEXT NOT NULL,
                auth_state TEXT DEFAULT 'UNKNOWN',
                fencing_token INTEGER DEFAULT 0,
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
                fencing_token INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (provider_profile_id) REFERENCES provider_profiles(id)
            )
        """)
        conn.commit()
        conn.close()

    def create_profile(self, profile_id: str, provider_id: str, account_id: str, name: str):
        conn = self.db.get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO provider_profiles (id, provider_id, account_id, name, auth_state, fencing_token) VALUES (?, ?, ?, ?, ?, ?)",
                (profile_id, provider_id, account_id, name, AuthState.UNKNOWN.value, 0),
            )
            conn.commit()
        finally:
            conn.close()

    def acquire_lock(self, profile_id: str, workflow_id: str) -> int:
        """Acquire the profile lease and return a monotonically increasing fence token.

        A second live workflow cannot take over the same provider profile. If a
        previous owner has expired, takeover increments the fencing generation,
        making the previous token invalid before the new worker proceeds.
        """
        now = datetime.now(timezone.utc)
        lease_expiry = (now + timedelta(seconds=self._LEASE_SECONDS)).timestamp()
        conn = self.db.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            profile = conn.execute(
                "SELECT account_id, fencing_token FROM provider_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if profile is None:
                raise LookupError(f"Provider profile is not registered: {profile_id}")

            session = conn.execute(
                "SELECT lock_owner, lease_expiry, fencing_token FROM sessions WHERE session_id = ?",
                (profile_id,),
            ).fetchone()
            if session and session["lock_owner"] not in (None, workflow_id):
                current_expiry = float(session["lease_expiry"] or 0)
                if current_expiry > now.timestamp():
                    raise RuntimeError(f"Provider profile is locked by workflow: {session['lock_owner']}")

            new_token = int(profile["fencing_token"]) + 1
            conn.execute(
                "UPDATE provider_profiles SET fencing_token = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_token, profile_id),
            )
            conn.execute("""
                INSERT INTO sessions
                (session_id, provider_profile_id, account_id, state, lock_owner, lease_expiry, fencing_token, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    account_id=excluded.account_id,
                    lock_owner=excluded.lock_owner,
                    lease_expiry=excluded.lease_expiry,
                    fencing_token=excluded.fencing_token,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                profile_id,
                profile_id,
                profile["account_id"],
                AuthState.UNKNOWN.value,
                workflow_id,
                lease_expiry,
                new_token,
            ))
            conn.commit()
            return new_token
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def renew_lock(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        """Renew an owned lease without changing its fencing generation."""
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=self._LEASE_SECONDS)).timestamp()
        conn = self.db.get_connection()
        try:
            cursor = conn.execute("""
                UPDATE sessions
                SET lease_expiry=?, updated_at=CURRENT_TIMESTAMP
                WHERE session_id=? AND lock_owner=? AND fencing_token=?
            """, (expiry, profile_id, workflow_id, fencing_token))
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def release_lock(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        """Release a lease only when the caller still owns the current fence."""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute("""
                UPDATE sessions
                SET lock_owner=NULL, lease_expiry=NULL, updated_at=CURRENT_TIMESTAMP
                WHERE session_id=? AND lock_owner=? AND fencing_token=?
            """, (profile_id, workflow_id, fencing_token))
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def validate_fencing_token(self, profile_id: str, fencing_token: int) -> bool:
        """Return whether a caller still owns the current fencing generation."""
        connection = self.db.get_connection()
        try:
            row = connection.execute(
                "SELECT fencing_token FROM provider_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            return row is not None and int(row[0]) == fencing_token
        finally:
            connection.close()

    def get_session_state(self, profile_id: str) -> str:
        conn = self.db.get_connection()
        try:
            row = conn.execute("SELECT auth_state FROM provider_profiles WHERE id = ?", (profile_id,)).fetchone()
            return row[0] if row else AuthState.UNKNOWN.value
        finally:
            conn.close()
