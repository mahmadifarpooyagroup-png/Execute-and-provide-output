import sqlite3
import os
import platform
from typing import Optional
from .database import AtrinDatabase


class SessionManager:
    def __init__(self, db: AtrinDatabase):
        self.db = db

    def create_profile(self, provider_id: str, account_id: str, name: str) -> int:
        """Create a new provider profile and return its ID."""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO provider_profiles (provider_id, account_id, name, auth_state, fencing_token)
                VALUES (?, ?, ?, 'UNKNOWN', 0)
                """,
                (provider_id, account_id, name)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def acquire_lock(self, profile_id: int, workflow_id: str) -> int:
        """
        Acquire a lock on a session for the given profile.
        Increments the fencing_token to prevent race conditions.
        Returns the new fencing_token value.
        """
        conn = self.db.get_connection()
        try:
            # Read current fencing_token
            row = conn.execute(
                "SELECT fencing_token FROM provider_profiles WHERE id = ?",
                (profile_id,)
            ).fetchone()
            
            if row is None:
                raise ValueError(f"Profile {profile_id} not found")
            
            current_token = row[0]
            new_token = current_token + 1
            
            # Create or update session with new fencing_token
            session_id = f"{workflow_id}_{profile_id}"
            
            # Check if session exists
            existing = conn.execute(
                "SELECT session_id FROM sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            
            if existing:
                conn.execute(
                    """
                    UPDATE sessions 
                    SET lock_owner = ?, state = 'ACTIVE', fencing_token = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = ?
                    """,
                    (workflow_id, new_token, session_id)
                )
            else:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, provider_profile_id, account_id, state, lock_owner, fencing_token)
                    SELECT ?, ?, account_id, 'ACTIVE', ?, ?
                    FROM provider_profiles WHERE id = ?
                    """,
                    (session_id, profile_id, workflow_id, new_token, profile_id)
                )
            
            # Update profile's fencing_token
            conn.execute(
                "UPDATE provider_profiles SET fencing_token = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_token, profile_id)
            )
            
            conn.commit()
            return new_token
        finally:
            conn.close()

    def release_lock(self, session_id: str) -> None:
        """Release the lock on a session."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                """
                UPDATE sessions 
                SET lock_owner = NULL, state = 'IDLE', updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (session_id,)
            )
            conn.commit()
        finally:
            conn.close()

    def get_session_state(self, profile_id: int) -> Optional[str]:
        """Get the current state of the session for a profile."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                """
                SELECT state FROM sessions 
                WHERE provider_profile_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (profile_id,)
            ).fetchone()
            
            return row[0] if row else None
        finally:
            conn.close()
