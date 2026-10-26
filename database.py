import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Generator


class Database:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(
        self,
        programs: list[dict],
        news_json_path: str,
        accounts_json_path: str,
    ) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS programs (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    host TEXT NOT NULL,
                    time TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    category TEXT NOT NULL,
                    category_id TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    icon TEXT NOT NULL,
                    url TEXT,
                    action_label TEXT,
                    poster TEXT
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    role TEXT NOT NULL CHECK (role IN ('journalist', 'editor')),
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    headline TEXT NOT NULL,
                    author TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    program_id INTEGER REFERENCES programs(id) ON DELETE SET NULL,
                    submitted_by INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                    reported_date TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('draft', 'published')),
                    review_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (review_status IN ('pending', 'approved', 'rejected')),
                    review_note TEXT NOT NULL DEFAULT '',
                    reviewed_by INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                    reviewed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS articles_status_date
                    ON articles (status, reported_date DESC, id DESC);
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    actor_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                    actor_username TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    target_type TEXT NOT NULL DEFAULT '',
                    target_id INTEGER,
                    summary TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS activity_log_created_at
                    ON activity_log (created_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            article_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(articles)")
            }
            if "review_status" not in article_columns:
                connection.execute(
                    "ALTER TABLE articles ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'"
                )
            if "review_note" not in article_columns:
                connection.execute(
                    "ALTER TABLE articles ADD COLUMN review_note TEXT NOT NULL DEFAULT ''"
                )
            if "reviewed_by" not in article_columns:
                connection.execute(
                    "ALTER TABLE articles ADD COLUMN reviewed_by INTEGER REFERENCES accounts(id) ON DELETE SET NULL"
                )
            if "reviewed_at" not in article_columns:
                connection.execute("ALTER TABLE articles ADD COLUMN reviewed_at TEXT")
            connection.execute(
                """
                UPDATE articles
                SET review_status = 'approved',
                    reviewed_at = COALESCE(reviewed_at, submitted_at)
                WHERE status = 'published' AND review_status = 'pending'
                """
            )

            program_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(programs)")
            }
            if "poster" not in program_columns:
                connection.execute("ALTER TABLE programs ADD COLUMN poster TEXT")

            for program in programs:
                connection.execute(
                    """
                    INSERT INTO programs (
                        id, title, host, time, status, category, category_id,
                        description, icon, url, action_label, poster
                    ) VALUES (
                        :id, :title, :host, :time, :status, :category, :category_id,
                        :description, :icon, :url, :action_label, :poster
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        host = excluded.host,
                        time = excluded.time,
                        status = excluded.status,
                        category = excluded.category,
                        category_id = excluded.category_id,
                        description = excluded.description,
                        icon = excluded.icon,
                        url = excluded.url,
                        action_label = excluded.action_label,
                        poster = excluded.poster
                    """,
                    {
                        **program,
                        "url": program.get("url"),
                        "action_label": program.get("action_label"),
                        "poster": program.get("poster"),
                    },
                )

            migrated = connection.execute(
                "SELECT 1 FROM app_metadata WHERE key = 'json_import_v1'"
            ).fetchone()
            if migrated is None:
                legacy_news = self._read_json(news_json_path)
                legacy_accounts = self._read_json(accounts_json_path)
                self._import_legacy_accounts(connection, legacy_accounts)
                self._import_legacy_articles(connection, legacy_news)
                connection.execute(
                    "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
                    ("json_import_v1", "complete"),
                )

    @staticmethod
    def _read_json(path: str) -> dict | None:
        try:
            with open(path, encoding="utf-8") as json_file:
                return json.load(json_file)
        except FileNotFoundError:
            return None

    @staticmethod
    def _import_legacy_accounts(
        connection: sqlite3.Connection, store: dict | None
    ) -> None:
        if not store:
            return
        for account in store.get("accounts", []):
            connection.execute(
                """
                INSERT OR IGNORE INTO accounts (
                    id, username, role, password_salt, password_hash, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account["id"],
                    account["username"],
                    account["role"],
                    account["password_salt"],
                    account["password_hash"],
                    int(account["active"]),
                    account["created_at"],
                ),
            )

    @staticmethod
    def _import_legacy_articles(
        connection: sqlite3.Connection, store: dict | None
    ) -> None:
        if not store:
            return
        for article in store.get("articles", []):
            connection.execute(
                """
                INSERT OR IGNORE INTO articles (
                    id, headline, author, body, source_url, program_id, submitted_by,
                    reported_date, submitted_at, status
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    article["id"],
                    article["headline"],
                    article["author"],
                    article["body"],
                    article.get("source_url", ""),
                    article["reported_date"],
                    article["submitted_at"],
                    article["status"],
                ),
            )

    def get_programs(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM programs ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_program_title(self, program_id: int | None) -> str | None:
        if program_id is None:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT title FROM programs WHERE id = ?", (program_id,)
            ).fetchone()
        return row["title"] if row else None

    def get_articles(self, published_only: bool = False) -> list[dict]:
        query = "SELECT * FROM articles"
        parameters: tuple = ()
        if published_only:
            query += " WHERE status = ?"
            parameters = ("published",)
        query += " ORDER BY reported_date DESC, id DESC"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def create_article(self, article: dict, actor_username: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO articles (
                    headline, author, body, source_url, program_id, submitted_by,
                    reported_date, submitted_at, status
                ) VALUES (
                    :headline, :author, :body, :source_url, :program_id, :submitted_by,
                    :reported_date, :submitted_at, :status
                )
                """,
                article,
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return the new article ID.")
            connection.execute(
                """
                INSERT INTO activity_log (
                    created_at, actor_account_id, actor_username, event_type,
                    target_type, target_id, summary
                ) VALUES (?, ?, ?, 'article_submitted', 'article', ?, ?)
                """,
                (
                    article["submitted_at"],
                    article["submitted_by"],
                    actor_username,
                    cursor.lastrowid,
                    f'Submitted report "{article["headline"]}" for editorial review.',
                ),
            )
            return cursor.lastrowid

    def publish_article(
        self, article_id: int, actor: dict, reviewed_at: str
    ) -> bool:
        with self.connect() as connection:
            article = connection.execute(
                "SELECT headline FROM articles WHERE id = ? AND review_status = 'pending'",
                (article_id,),
            ).fetchone()
            if article is None:
                return False
            cursor = connection.execute(
                """
                UPDATE articles
                SET status = 'published', review_status = 'approved',
                    review_note = '', reviewed_by = ?, reviewed_at = ?
                WHERE id = ? AND status = 'draft' AND review_status = 'pending'
                """,
                (actor["id"], reviewed_at, article_id),
            )
            if cursor.rowcount != 1:
                return False
            self._insert_activity(
                connection,
                reviewed_at,
                actor["id"],
                actor["username"],
                "article_approved",
                "article",
                article_id,
                f'Approved and published report "{article["headline"]}".',
            )
            return True

    def reject_article(
        self, article_id: int, actor: dict, reviewed_at: str, reason: str
    ) -> bool:
        with self.connect() as connection:
            article = connection.execute(
                "SELECT headline FROM articles WHERE id = ? AND review_status = 'pending'",
                (article_id,),
            ).fetchone()
            if article is None:
                return False
            cursor = connection.execute(
                """
                UPDATE articles
                SET review_status = 'rejected', review_note = ?,
                    reviewed_by = ?, reviewed_at = ?
                WHERE id = ? AND status = 'draft' AND review_status = 'pending'
                """,
                (reason, actor["id"], reviewed_at, article_id),
            )
            if cursor.rowcount != 1:
                return False
            self._insert_activity(
                connection,
                reviewed_at,
                actor["id"],
                actor["username"],
                "article_rejected",
                "article",
                article_id,
                f'Rejected report "{article["headline"]}": {reason}',
            )
            return True

    @staticmethod
    def _insert_activity(
        connection: sqlite3.Connection,
        created_at: str,
        actor_account_id: int | None,
        actor_username: str,
        event_type: str,
        target_type: str,
        target_id: int | None,
        summary: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO activity_log (
                created_at, actor_account_id, actor_username, event_type,
                target_type, target_id, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                actor_account_id,
                actor_username,
                event_type,
                target_type,
                target_id,
                summary,
            ),
        )

    def record_activity(
        self,
        created_at: str,
        actor_account_id: int | None,
        actor_username: str,
        event_type: str,
        summary: str,
        target_type: str = "",
        target_id: int | None = None,
    ) -> None:
        with self.connect() as connection:
            self._insert_activity(
                connection,
                created_at,
                actor_account_id,
                actor_username,
                event_type,
                target_type,
                target_id,
                summary,
            )

    def get_activity(self, limit: int = 250) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM activity_log
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_account(self, account_id: int, active_only: bool = False) -> dict | None:
        query = "SELECT * FROM accounts WHERE id = ?"
        if active_only:
            query += " AND active = 1"
        with self.connect() as connection:
            row = connection.execute(query, (account_id,)).fetchone()
        return dict(row) if row else None

    def find_account_by_username(self, username: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM accounts WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def get_accounts(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM accounts ORDER BY active DESC, username COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def has_accounts(self) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone()
        return row is not None

    def create_initial_editor(self, account: dict) -> int | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM accounts LIMIT 1"
            ).fetchone()
            if existing:
                return None
            cursor = connection.execute(
                """
                INSERT INTO accounts (
                    username, role, password_salt, password_hash, active, created_at
                ) VALUES (:username, 'editor', :password_salt, :password_hash, 1, :created_at)
                """,
                account,
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return the new account ID.")
            return cursor.lastrowid

    def create_account(self, account: dict) -> int | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM accounts WHERE username = ? COLLATE NOCASE",
                (account["username"],),
            ).fetchone()
            if exists:
                return None
            cursor = connection.execute(
                """
                INSERT INTO accounts (
                    username, role, password_salt, password_hash, active, created_at
                ) VALUES (:username, :role, :password_salt, :password_hash, 1, :created_at)
                """,
                account,
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return the new account ID.")
            return cursor.lastrowid

    def update_account(
        self,
        account_id: int,
        username: str,
        role: str,
        active: bool,
        password_salt: str | None,
        password_hash: str | None,
    ) -> str:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            account = connection.execute(
                "SELECT role, active FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if account is None:
                return "not_found"
            duplicate = connection.execute(
                "SELECT 1 FROM accounts WHERE id != ? AND username = ? COLLATE NOCASE",
                (account_id, username),
            ).fetchone()
            if duplicate:
                return "duplicate"
            if (
                account["role"] == "editor"
                and account["active"]
                and (role != "editor" or not active)
            ):
                other_editor = connection.execute(
                    """
                    SELECT 1 FROM accounts
                    WHERE id != ? AND role = 'editor' AND active = 1
                    LIMIT 1
                    """,
                    (account_id,),
                ).fetchone()
                if other_editor is None:
                    return "last_editor"

            if password_salt is None or password_hash is None:
                connection.execute(
                    """
                    UPDATE accounts SET username = ?, role = ?, active = ?
                    WHERE id = ?
                    """,
                    (username, role, int(active), account_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE accounts
                    SET username = ?, role = ?, active = ?,
                        password_salt = ?, password_hash = ?
                    WHERE id = ?
                    """,
                    (username, role, int(active), password_salt, password_hash, account_id),
                )
            return "updated"
