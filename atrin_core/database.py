import sqlite3
import os

class AtrinDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_ledger (
                idempotency_key TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                workflow_id TEXT,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload TEXT,
                prev_hash TEXT,
                entry_hash TEXT NOT NULL
            )
        """)
        
        # Phase 3: provider_profiles table with fencing_token
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_profiles (
                id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                name TEXT NOT NULL,
                auth_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                fencing_token INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Phase 3: sessions table with fencing_token and lock management
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                provider_profile_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'NOT_AUTHENTICATED',
                lock_owner TEXT,
                lease_expiry TIMESTAMP,
                fencing_token INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (provider_profile_id) REFERENCES provider_profiles(id)
            )
        """)
        
        conn.commit()
        conn.close()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn
