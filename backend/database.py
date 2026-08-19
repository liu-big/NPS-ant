import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from passlib.context import CryptContext

from typing import Annotated

from fastapi import Depends

from config import Settings, get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portal_tunnel_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    client_id INTEGER NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    service TEXT NOT NULL DEFAULT 'tcp',
    nps_tunnel_id INTEGER NOT NULL,
    public_host TEXT NOT NULL,
    public_port INTEGER NOT NULL,
    target_host TEXT NOT NULL,
    target_port INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    expire_at TEXT,
    deleted_at TEXT,
    remark TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(user_id) REFERENCES portal_users(id)
);

CREATE TABLE IF NOT EXISTS portal_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tunnel_user ON portal_tunnel_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_tunnel_status ON portal_tunnel_sessions(status);
CREATE INDEX IF NOT EXISTS idx_audit_created ON portal_audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_username ON portal_audit_logs(username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON portal_audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_role ON portal_audit_logs(role);
CREATE INDEX IF NOT EXISTS idx_audit_target_type ON portal_audit_logs(target_type);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        tunnel_cols = {row[1] for row in conn.execute("PRAGMA table_info(portal_tunnel_sessions)")}
        if "ttl_minutes" not in tunnel_cols:
            conn.execute("ALTER TABLE portal_tunnel_sessions ADD COLUMN ttl_minutes INTEGER")
        if "updated_at" not in tunnel_cols:
            conn.execute("ALTER TABLE portal_tunnel_sessions ADD COLUMN updated_at TEXT")
        if "released_at" not in tunnel_cols:
            conn.execute("ALTER TABLE portal_tunnel_sessions ADD COLUMN released_at TEXT")
        if "release_reason" not in tunnel_cols:
            conn.execute("ALTER TABLE portal_tunnel_sessions ADD COLUMN release_reason TEXT")

    def init_schema(self, settings: Settings) -> None:
        with self.connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate_schema(conn)
            row = conn.execute("SELECT COUNT(*) AS c FROM portal_users").fetchone()
            if row["c"] == 0:
                now = utc_now()
                conn.execute(
                    """
                    INSERT INTO portal_users (username, password_hash, role, status, created_at, updated_at)
                    VALUES (?, ?, 'admin', 'active', ?, ?)
                    """,
                    (
                        settings.portal_username,
                        hash_password(settings.portal_password),
                        now,
                        now,
                    ),
                )

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM portal_users WHERE username = ?",
                (username,),
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM portal_users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, username, role, status, created_at, updated_at FROM portal_users ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def create_user(self, username: str, password: str, role: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO portal_users (username, password_hash, role, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (username, hash_password(password), role, now, now),
            )
            user_id = cur.lastrowid
        return self.get_user_by_id(user_id)  # type: ignore[return-value]

    def update_user(self, user_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"username", "role", "status"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return self.get_user_by_id(user_id)
        updates["updated_at"] = utc_now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE portal_users SET {set_clause} WHERE id = ?", values)
        return self.get_user_by_id(user_id)

    def reset_password(self, user_id: int, password: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE portal_users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(password), utc_now(), user_id),
            )
            return cur.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM portal_users WHERE id = ?", (user_id,))
            return cur.rowcount > 0

    def create_tunnel_session(self, **data: Any) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO portal_tunnel_sessions (
                    user_id, client_id, device_name, service, nps_tunnel_id,
                    public_host, public_port, target_host, target_port,
                    status, created_at, updated_at, expire_at, remark, ttl_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (
                    data["user_id"],
                    data["client_id"],
                    data.get("device_name", ""),
                    data.get("service", "tcp"),
                    data["nps_tunnel_id"],
                    data["public_host"],
                    data["public_port"],
                    data["target_host"],
                    data["target_port"],
                    now,
                    now,
                    data.get("expire_at"),
                    data.get("remark", ""),
                    data.get("ttl_minutes"),
                ),
            )
            session_id = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM portal_tunnel_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return dict(row)

    def get_tunnel_session(self, session_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM portal_tunnel_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_tunnel_sessions(
        self,
        user_id: int | None = None,
        include_deleted: bool = False,
        status: str | None = None,
        keyword: str | None = None,
        exclude_statuses: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if user_id is not None:
            conditions.append("t.user_id = ?")
            params.append(user_id)
        if not include_deleted:
            conditions.append(
                "t.status IN ('running', 'expired', 'released', 'deleted', 'failed', 'cleanup_failed')"
            )
        if exclude_statuses:
            placeholders = ",".join("?" for _ in exclude_statuses)
            conditions.append(f"t.status NOT IN ({placeholders})")
            params.extend(exclude_statuses)
        if status and status.strip():
            conditions.append("t.status = ?")
            params.append(status.strip().lower())
        if keyword and keyword.strip():
            kw = f"%{keyword.strip()}%"
            conditions.append(
                "(t.device_name LIKE ? OR t.remark LIKE ? OR CAST(t.public_port AS TEXT) LIKE ? "
                "OR t.target_host LIKE ? OR CAST(t.target_port AS TEXT) LIKE ? "
                "OR t.public_host LIKE ? OR u.username LIKE ?)"
            )
            params.extend([kw, kw, kw, kw, kw, kw, kw])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT t.*, u.username
                FROM portal_tunnel_sessions t
                JOIN portal_users u ON u.id = t.user_id
                {where}
                ORDER BY t.id DESC
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def list_expired_active_sessions(self) -> list[dict[str, Any]]:
        now = utc_now()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM portal_tunnel_sessions
                WHERE status = 'running'
                  AND expire_at IS NOT NULL
                  AND expire_at <= ?
                """,
                (now,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_reserved_public_ports(self) -> set[int]:
        """Ports held by running or cleanup_failed sessions (not yet released)."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT public_port FROM portal_tunnel_sessions
                WHERE status IN ('running', 'cleanup_failed')
                  AND public_port IS NOT NULL
                  AND public_port > 0
                """
            ).fetchall()
        return {int(r["public_port"]) for r in rows}

    def count_running_mappings(self, user_id: int | None = None) -> int:
        with self.connect() as conn:
            conditions = ["status = 'running'"]
            params: list[Any] = []
            if user_id is not None:
                conditions.append("user_id = ?")
                params.append(user_id)
            where = " AND ".join(conditions)
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM portal_tunnel_sessions WHERE {where}",
                params,
            ).fetchone()
        return int(row["c"])

    def mark_invalid_tunnel_sessions(self, settings: Settings) -> list[dict[str, Any]]:
        """Mark sessions with invalid public_port as failed."""
        auto_start, auto_end = settings.get_auto_port_range()
        blocklist = settings.get_auto_port_blocklist()
        now = utc_now()

        invalid_condition = """
            status = 'running'
            AND (
                public_port IS NULL
                OR public_port <= 0
                OR public_port IN ({blocklist})
                OR public_port < ?
                OR public_port > ?
            )
        """.format(
            blocklist=",".join(str(p) for p in sorted(blocklist)) or "-1"
        )
        params = (auto_start, auto_end)

        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM portal_tunnel_sessions WHERE {invalid_condition}",
                params,
            ).fetchall()
            if not rows:
                return []
            conn.execute(
                f"""
                UPDATE portal_tunnel_sessions
                SET status = 'failed',
                    deleted_at = ?,
                    released_at = ?,
                    release_reason = 'invalid_port',
                    updated_at = ?,
                    remark = COALESCE(remark, '') || ' | invalid public_port'
                WHERE {invalid_condition}
                """,
                (now, now, now, *params),
            )
        return [dict(r) for r in rows]

    def mark_tunnel_deleted(
        self,
        session_id: int,
        status: str = "deleted",
        release_reason: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE portal_tunnel_sessions
                SET status = ?,
                    deleted_at = ?,
                    released_at = ?,
                    release_reason = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, now, now, release_reason, now, session_id),
            )

    def add_audit_log(
        self,
        user_id: int | None,
        username: str,
        role: str,
        action: str,
        target_type: str = "",
        target_id: str = "",
        detail: str = "",
        ip: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portal_audit_logs
                (user_id, username, role, action, target_type, target_id, detail, ip, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, role, action, target_type, target_id, detail, ip, utc_now()),
            )

    def search_audit_logs(
        self,
        *,
        username: str | None = None,
        role: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        keyword: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        params: list[Any] = []

        if username and username.strip():
            conditions.append("username LIKE ?")
            params.append(f"%{username.strip()}%")
        if role and role.strip():
            conditions.append("role = ?")
            params.append(role.strip())
        if action and action.strip():
            conditions.append("action = ?")
            params.append(action.strip())
        if target_type and target_type.strip():
            conditions.append("target_type = ?")
            params.append(target_type.strip())
        if keyword and keyword.strip():
            kw = f"%{keyword.strip()}%"
            conditions.append("(detail LIKE ? OR target_id LIKE ? OR username LIKE ? OR action LIKE ?)")
            params.extend([kw, kw, kw, kw])
        if start_at:
            conditions.append("created_at >= ?")
            params.append(start_at)
        if end_at:
            conditions.append("created_at <= ?")
            params.append(end_at)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM portal_audit_logs {where}",
                params,
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT * FROM portal_audit_logs
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return {"items": [dict(r) for r in rows], "total": int(total_row["c"])}

    def list_audit_log_actions(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT action FROM portal_audit_logs
                WHERE action != ''
                ORDER BY action
                """
            ).fetchall()
        return [str(r["action"]) for r in rows]

    def delete_audit_logs_before(self, cutoff_at: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM portal_audit_logs WHERE created_at < ?",
                (cutoff_at,),
            )
            return int(cur.rowcount)


_db: Database | None = None


def init_db(settings: Settings) -> Database:
    global _db
    if _db is None:
        _db = Database(Path(settings.data_dir) / "portal.db")
    return _db


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Database:
    return init_db(settings)
