import json
import sqlite3
from pathlib import Path

from config.settings import MAX_HISTORY_MESSAGES

DB_PATH = Path(__file__).parent.parent / "data" / "lena.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                role       TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                mode       TEXT,
                channel    TEXT    DEFAULT 'general',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS corrections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                original   TEXT    NOT NULL,
                corrected  TEXT    NOT NULL,
                category   TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id            INTEGER NOT NULL,
                session_date       TEXT    NOT NULL,
                session_start_ts   INTEGER NOT NULL,
                session_end_ts     INTEGER,
                phase_executed     TEXT,
                mood_score         INTEGER,
                summary_json       TEXT,
                article_potential  TEXT,
                created_at         INTEGER DEFAULT (strftime('%s','now'))
            );
            CREATE TABLE IF NOT EXISTS raw_logs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                session_date TEXT    NOT NULL,
                turn_index   INTEGER NOT NULL,
                role         TEXT    NOT NULL,
                content      TEXT    NOT NULL,
                ts           INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS daily_state (
                user_id           INTEGER PRIMARY KEY,
                active            INTEGER NOT NULL,
                session_date      TEXT,
                session_start_ts  INTEGER,
                phase             INTEGER,
                depth             TEXT,
                turn_count        INTEGER DEFAULT 0,
                phase2_turn_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS usage (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                service       TEXT NOT NULL,
                model         TEXT,
                input_tokens  INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                count         INTEGER DEFAULT 1,
                cost_usd      REAL DEFAULT 0,
                ts            INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_date ON sessions(user_id, session_date);
            CREATE INDEX IF NOT EXISTS idx_raw_logs_session ON raw_logs(user_id, session_date, turn_index);
            CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
        """)
    _migrate_add_channel_column()
    _migrate_from_json()


# ---------------------------------------------------------------------------
# Daily session helpers
# ---------------------------------------------------------------------------

def get_daily_state(user_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_state WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def set_daily_state(user_id: int, **fields) -> None:
    existing = get_daily_state(user_id)
    if existing:
        keys = ", ".join(f"{k} = ?" for k in fields)
        with _conn() as conn:
            conn.execute(
                f"UPDATE daily_state SET {keys} WHERE user_id = ?",
                (*fields.values(), user_id),
            )
    else:
        cols = ["user_id"] + list(fields.keys())
        placeholders = ",".join("?" * len(cols))
        with _conn() as conn:
            conn.execute(
                f"INSERT INTO daily_state ({','.join(cols)}) VALUES ({placeholders})",
                (user_id, *fields.values()),
            )


def clear_daily_state(user_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM daily_state WHERE user_id = ?", (user_id,))


def append_raw_log(user_id: int, session_date: str, role: str, content: str, ts: int) -> int:
    with _conn() as conn:
        next_idx = conn.execute(
            "SELECT COALESCE(MAX(turn_index)+1, 0) FROM raw_logs "
            "WHERE user_id = ? AND session_date = ?",
            (user_id, session_date),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO raw_logs (user_id, session_date, turn_index, role, content, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, session_date, next_idx, role, content, ts),
        )
    return next_idx


def get_raw_log(user_id: int, session_date: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content, ts FROM raw_logs "
            "WHERE user_id = ? AND session_date = ? ORDER BY turn_index",
            (user_id, session_date),
        ).fetchall()
    return [dict(r) for r in rows]


def save_session(
    user_id: int,
    session_date: str,
    session_start_ts: int,
    session_end_ts: int,
    phase_executed: str,
    mood_score: int | None,
    summary_json: str,
    article_potential: str | None,
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, session_date, session_start_ts, session_end_ts, "
            "phase_executed, mood_score, summary_json, article_potential) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, session_date, session_start_ts, session_end_ts,
             phase_executed, mood_score, summary_json, article_potential),
        )


def log_usage(
    service: str,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    count: int = 1,
    cost_usd: float = 0.0,
) -> None:
    import time
    with _conn() as conn:
        conn.execute(
            "INSERT INTO usage (service, model, input_tokens, output_tokens, count, cost_usd, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (service, model, input_tokens, output_tokens, count, cost_usd, int(time.time())),
        )


def usage_summary(since_ts: int) -> list[dict]:
    """Aggregated usage by service since a given unix timestamp."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT service, "
            "       COALESCE(SUM(input_tokens),0) AS input_tokens, "
            "       COALESCE(SUM(output_tokens),0) AS output_tokens, "
            "       COALESCE(SUM(count),0) AS count, "
            "       COALESCE(SUM(cost_usd),0) AS cost_usd "
            "FROM usage WHERE ts >= ? GROUP BY service",
            (since_ts,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_sessions(user_id: int, limit: int = 3) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT session_date, summary_json FROM sessions "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_history(user_id: int, channel: str = "general") -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE user_id = ? AND channel = ? ORDER BY id DESC LIMIT ?",
            (user_id, channel, MAX_HISTORY_MESSAGES),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def add_message(
    user_id: int, role: str, content: str, mode: str | None = None, channel: str = "general"
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO messages (user_id, role, content, mode, channel) VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, mode, channel),
        )


def add_correction(user_id: int, original: str, corrected: str, category: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO corrections (user_id, original, corrected, category) VALUES (?, ?, ?, ?)",
            (user_id, original, corrected, category),
        )


def _migrate_add_channel_column() -> None:
    """Add 'channel' column to legacy messages table if missing; ensure channel index."""
    with _conn() as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "channel" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN channel TEXT DEFAULT 'general'")
            print("[DB] Migrated: added 'channel' column to messages")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_channel "
            "ON messages(user_id, channel, id)"
        )


def _migrate_from_json() -> None:
    """One-time: import existing JSON conversation files into SQLite."""
    json_dir = DB_PATH.parent / "conversations"
    if not json_dir.exists():
        return

    with _conn() as conn:
        for json_file in json_dir.glob("*.json"):
            try:
                user_id = int(json_file.stem)
            except ValueError:
                continue

            already = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            if already:
                continue

            try:
                messages = json.loads(json_file.read_text(encoding="utf-8"))
                conn.executemany(
                    "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                    [(user_id, m["role"], m["content"]) for m in messages],
                )
                print(f"[DB] Migrated {len(messages)} messages for user {user_id}")
            except Exception as e:
                print(f"[DB] Migration error for {json_file}: {e}")
