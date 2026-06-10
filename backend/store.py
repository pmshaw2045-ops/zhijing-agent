"""
SQLiteBackend — 结构化记忆存储

使用WAL模式，并发安全。与现有JSON存储完全兼容。
"""
import json
import sqlite3
import os
import threading
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "zhijing.db"


class SQLiteBackend:
    """SQLite 记忆存储后端，WAL模式（读写并发安全）"""

    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                data JSON NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL DEFAULT (unixepoch())
            );
            CREATE TABLE IF NOT EXISTS long_term (
                key TEXT PRIMARY KEY,
                value JSON NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL DEFAULT (unixepoch())
            );
            CREATE TABLE IF NOT EXISTS memory_vectors (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                vector BLOB NOT NULL,
                metadata JSON NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL DEFAULT (unixepoch())
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);
            CREATE INDEX IF NOT EXISTS idx_mv_session ON memory_vectors(session_id);
            CREATE INDEX IF NOT EXISTS idx_mv_created ON memory_vectors(created_at);
        """)
        conn.commit()

    # ── Sessions ──

    def get_session(self, session_id: str) -> dict:
        row = self._get_conn().execute(
            "SELECT data FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return json.loads(row[0]) if row else {}

    def set_session(self, session_id: str, data: dict):
        self._get_conn().execute(
            "INSERT OR REPLACE INTO sessions (id, data, updated_at) VALUES (?, ?, unixepoch())",
            (session_id, json.dumps(data, ensure_ascii=False))
        )
        self._get_conn().commit()

    def has_session(self, session_id: str) -> bool:
        row = self._get_conn().execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row is not None

    def session_count(self) -> int:
        row = self._get_conn().execute("SELECT COUNT(*) FROM sessions").fetchone()
        return row[0] if row else 0

    # ── Long-term ──

    def get_long_term(self) -> dict:
        """加载所有长期记忆为 dict"""
        rows = self._get_conn().execute("SELECT key, value FROM long_term").fetchall()
        # 重建嵌套结构
        lt = {"domains": {}, "brands": {}, "seasons": {},
              "platforms": {}, "user_preferences": {}, "knowledge_snippets": []}
        for r in rows:
            key = r["key"]
            val = json.loads(r["value"]) if isinstance(r["value"], str) else r["value"]
            if key.startswith("domain:"):
                lt["domains"][key[7:]] = val
            elif key.startswith("brand:"):
                lt["brands"][key[6:]] = val
            elif key.startswith("season:"):
                lt["seasons"][key[7:]] = val
            elif key.startswith("platform:"):
                lt["platforms"][key[9:]] = val
            elif key.startswith("pref:"):
                lt["user_preferences"][key[5:]] = val
            elif key == "knowledge_snippets":
                lt["knowledge_snippets"] = val if isinstance(val, list) else []
        return lt

    def set_long_term(self, lt: dict):
        conn = self._get_conn()
        conn.execute("DELETE FROM long_term")
        data = []
        for category, prefix in [("domains", "domain:"), ("brands", "brand:"),
                                   ("seasons", "season:"), ("platforms", "platform:"),
                                   ("user_preferences", "pref:")]:
            for k, v in lt.get(category, {}).items():
                data.append((f"{prefix}{k}", json.dumps(v, ensure_ascii=False)))
        if lt.get("knowledge_snippets"):
            data.append(("knowledge_snippets", json.dumps(lt["knowledge_snippets"], ensure_ascii=False)))
        conn.executemany(
            "INSERT OR REPLACE INTO long_term (key, value, updated_at) VALUES (?, ?, unixepoch())",
            data
        )
        conn.commit()

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ── Memory Vectors ──

    def save_vector(self, vector_id: str, session_id: str,
                    vector: list[float], metadata: dict):
        """保存一条向量记录"""
        import json
        vec_json = json.dumps(vector)
        meta_json = json.dumps(metadata, ensure_ascii=False)
        self._get_conn().execute(
            "INSERT OR REPLACE INTO memory_vectors (id, session_id, vector, metadata, created_at) "
            "VALUES (?, ?, ?, ?, unixepoch())",
            (vector_id, session_id, vec_json, meta_json)
        )
        self._get_conn().commit()

    def get_vectors(self, since_days: int = 30, limit: int = 500) -> list[dict]:
        """获取最近 N 天的向量记录"""
        import json
        rows = self._get_conn().execute(
            "SELECT id, session_id, vector, metadata, created_at "
            "FROM memory_vectors WHERE created_at > unixepoch() - ? "
            "ORDER BY created_at DESC LIMIT ?",
            (since_days * 86400, limit)
        ).fetchall()
        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "session_id": r["session_id"],
                "vector": json.loads(r["vector"]),
                "metadata": json.loads(r["metadata"]),
                "created_at": r["created_at"],
            })
        return results


def migrate_json_to_sqlite(json_path: Path = DATA_DIR / "memory_store.json",
                           db_path: Path | None = None) -> int:
    """从JSON文件迁移到SQLite，返回迁移的会话数"""
    if not json_path.exists():
        return 0

    with open(json_path) as f:
        data = json.load(f)

    backend = SQLiteBackend(db_path or DB_PATH)
    count = 0

    for sid, sess in data.get("sessions", {}).items():
        backend.set_session(sid, sess)
        count += 1

    if data.get("long_term"):
        backend.set_long_term(data["long_term"])

    return count
