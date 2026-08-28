import sqlite3
import time
from typing import Optional
from .database import AtrinDatabase
from .models import AuthState

class SessionManager:
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
                fencing_token INTEGER DEFAULT 0
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
                fencing_token INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def create_profile(self, profile_id: str, provider_id: str, account_id: str, name: str):
        conn = self.db.get_connection()
        conn.execute(
            "INSERT OR IGNORE INTO provider_profiles (id, provider_id, account_id, name, auth_state, fencing_token) VALUES (?, ?, ?, ?, ?, ?)",
            (profile_id, provider_id, account_id, name, AuthState.UNKNOWN.value, 0)
        )
        conn.commit()
        conn.close()

    def acquire_lock(self, profile_id: str, workflow_id: str) -> int:
        conn = self.db.get_connection()
        cursor = conn.execute("SELECT fencing_token FROM provider_profiles WHERE id = ?", (profile_id,))
        row = cursor.fetchone()
        current_token = row[0] if row else 0
        
        new_token = current_token + 1
        conn.execute("UPDATE provider_profiles SET fencing_token = ? WHERE id = ?", (new_token, profile_id))
        conn.commit()
        conn.close()
        return new_token

    def get_session_state(self, profile_id: str) -> str:
        conn = self.db.get_connection()
        cursor = conn.execute("SELECT auth_state FROM provider_profiles WHERE id = ?", (profile_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else AuthState.UNKNOWN.value
