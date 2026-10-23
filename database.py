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
                    action_label TEXT
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
                    status TEXT NOT NULL CHECK (status IN ('draft', 'published'))
                );
                CREATE INDEX IF NOT EXISTS articles_status_date
                    ON articles (status, reported_date DESC, id DESC);
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            for program in programs:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO programs (
                        id, title, host, time, status, category, category_id,
                        description, icon, url, action_label
                    ) VALUES (
                        :id, :title, :host, :time, :status, :category, :category_id,
                        :description, :icon, :url, :action_label
                    )
                    """,
                    {
                        **program,
                        "url": program.get("url"),
                        "action_label": program.get("action_label"),
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

    def create_article(self, article: dict) -> int:
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
            return cursor.lastrowid

    def publish_article(self, article_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE articles SET status = 'published' WHERE id = ? AND status = 'draft'",
                (article_id,),
            )
            return cursor.rowcount == 1

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
