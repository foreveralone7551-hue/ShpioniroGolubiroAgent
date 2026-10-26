"""SQLite-хранилище. Только стандартная библиотека: sqlite3 + asyncio.to_thread."""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS owners (
    user_id        INTEGER PRIMARY KEY,
    chat_id        INTEGER NOT NULL,           -- личка владельца с ботом
    connection_id  TEXT    NOT NULL,           -- business_connection_id
    first_name     TEXT,
    last_name      TEXT,
    username       TEXT,
    connected_at   INTEGER NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1,
    notif_self     INTEGER NOT NULL DEFAULT 0,
    notif_edit     INTEGER NOT NULL DEFAULT 1,
    notif_delete   INTEGER NOT NULL DEFAULT 1,
    notif_bots     INTEGER NOT NULL DEFAULT 0,
    spy_on         INTEGER NOT NULL DEFAULT 1,
    spy_any        INTEGER NOT NULL DEFAULT 0,
    topic_events   INTEGER,
    topic_menu     INTEGER,
    topics_tried   INTEGER NOT NULL DEFAULT 0,
    clock_on       INTEGER NOT NULL DEFAULT 0,
    clock_base     TEXT,
    clock_last     TEXT
);

CREATE TABLE IF NOT EXISTS chats (
    owner_id  INTEGER NOT NULL,
    chat_id   INTEGER NOT NULL,
    name      TEXT,
    username  TEXT,
    is_bot    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, chat_id)
);

CREATE TABLE IF NOT EXISTS messages (
    owner_id         INTEGER NOT NULL,
    chat_id          INTEGER NOT NULL,
    message_id       INTEGER NOT NULL,
    sender_id        INTEGER,
    sender_name      TEXT,
    sender_username  TEXT,
    is_own           INTEGER NOT NULL DEFAULT 0,
    text             TEXT,
    media_type       TEXT,
    file_id          TEXT,
    file_unique_id   TEXT,
    date             INTEGER NOT NULL,
    PRIMARY KEY (owner_id, chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER NOT NULL,
    kind        TEXT    NOT NULL,              -- edit | delete | spy
    ts          INTEGER NOT NULL,
    label       TEXT    NOT NULL,
    html        TEXT    NOT NULL,
    media_type  TEXT,
    file_id     TEXT,
    ref         TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_owner ON events(owner_id, id DESC);

CREATE TABLE IF NOT EXISTS muted (
    owner_id INTEGER NOT NULL,
    chat_id  INTEGER NOT NULL,
    PRIMARY KEY (owner_id, chat_id)
);
"""

# Поля owners, которые разрешено менять через set_flag / toggle_flag
FLAGS = {"notif_self", "notif_edit", "notif_delete", "notif_bots", "spy_on", "spy_any", "clock_on"}

Row = dict[str, Any]


class Database:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---- низкий уровень -------------------------------------------------
    def _exec(self, sql: str, params: tuple, fetch: Optional[str]) -> Any:
        with self._lock:
            cur = self._conn.execute(sql, params)
            if fetch == "one":
                row = cur.fetchone()
                self._conn.commit()
                return dict(row) if row else None
            if fetch == "all":
                rows = cur.fetchall()
                self._conn.commit()
                return [dict(r) for r in rows]
            self._conn.commit()
            return cur.lastrowid

    async def run(self, sql: str, params: tuple = (), fetch: Optional[str] = None) -> Any:
        return await asyncio.to_thread(self._exec, sql, params, fetch)

    # ---- владельцы ------------------------------------------------------
    async def upsert_owner(
        self, user_id: int, chat_id: int, connection_id: str,
        first_name: Optional[str], last_name: Optional[str], username: Optional[str],
        is_active: bool,
    ) -> None:
        await self.run(
            """INSERT INTO owners(user_id, chat_id, connection_id, first_name, last_name,
                                  username, connected_at, is_active)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   chat_id=excluded.chat_id,
                   connection_id=excluded.connection_id,
                   first_name=excluded.first_name,
                   last_name=excluded.last_name,
                   username=excluded.username,
                   connected_at=CASE WHEN owners.is_active=0 AND excluded.is_active=1
                                     THEN excluded.connected_at ELSE owners.connected_at END,
                   is_active=excluded.is_active""",
            (user_id, chat_id, connection_id, first_name, last_name, username,
             int(time.time()), int(is_active)),
        )

    async def get_owner(self, user_id: int) -> Optional[Row]:
        return await self.run("SELECT * FROM owners WHERE user_id=?", (user_id,), "one")

    async def get_owner_by_connection(self, connection_id: str) -> Optional[Row]:
        return await self.run("SELECT * FROM owners WHERE connection_id=?", (connection_id,), "one")

    async def toggle_flag(self, user_id: int, field: str) -> bool:
        if field not in FLAGS:
            raise ValueError(field)
        await self.run(f"UPDATE owners SET {field} = 1 - {field} WHERE user_id=?", (user_id,))
        row = await self.get_owner(user_id)
        return bool(row and row[field])

    async def set_flag(self, user_id: int, field: str, value: bool) -> None:
        if field not in FLAGS:
            raise ValueError(field)
        await self.run(f"UPDATE owners SET {field}=? WHERE user_id=?", (int(value), user_id))

    async def set_topics(self, user_id: int, events: Optional[int], menu: Optional[int]) -> None:
        await self.run(
            "UPDATE owners SET topic_events=?, topic_menu=?, topics_tried=1 WHERE user_id=?",
            (events, menu, user_id),
        )

    async def set_clock(self, user_id: int, on: bool, base: Optional[str] = None) -> None:
        await self.run(
            "UPDATE owners SET clock_on=?, clock_base=COALESCE(?, clock_base), clock_last=NULL WHERE user_id=?",
            (int(on), base, user_id),
        )

    async def set_clock_last(self, user_id: int, stamp: str) -> None:
        await self.run("UPDATE owners SET clock_last=? WHERE user_id=?", (stamp, user_id))

    async def clock_owners(self) -> list[Row]:
        return await self.run("SELECT * FROM owners WHERE clock_on=1 AND is_active=1", (), "all")

    # ---- чаты -----------------------------------------------------------
    async def upsert_chat(self, owner_id: int, chat_id: int, name: str,
                          username: Optional[str], is_bot: bool) -> None:
        await self.run(
            """INSERT INTO chats(owner_id, chat_id, name, username, is_bot) VALUES (?,?,?,?,?)
               ON CONFLICT(owner_id, chat_id) DO UPDATE SET
                   name=excluded.name, username=excluded.username, is_bot=excluded.is_bot""",
            (owner_id, chat_id, name, username, int(is_bot)),
        )

    async def get_chat(self, owner_id: int, chat_id: int) -> Optional[Row]:
        return await self.run(
            "SELECT * FROM chats WHERE owner_id=? AND chat_id=?", (owner_id, chat_id), "one")

    # ---- сообщения ------------------------------------------------------
    async def save_message(
        self, owner_id: int, chat_id: int, message_id: int, sender_id: Optional[int],
        sender_name: str, sender_username: Optional[str], is_own: bool, text: str,
        media_type: Optional[str], file_id: Optional[str], file_unique_id: Optional[str],
        date: int,
    ) -> None:
        await self.run(
            """INSERT OR REPLACE INTO messages(owner_id, chat_id, message_id, sender_id,
                   sender_name, sender_username, is_own, text, media_type, file_id,
                   file_unique_id, date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (owner_id, chat_id, message_id, sender_id, sender_name, sender_username,
             int(is_own), text, media_type, file_id, file_unique_id, date),
        )

    async def get_message(self, owner_id: int, chat_id: int, message_id: int) -> Optional[Row]:
        return await self.run(
            "SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND message_id=?",
            (owner_id, chat_id, message_id), "one")

    async def delete_message(self, owner_id: int, chat_id: int, message_id: int) -> None:
        await self.run(
            "DELETE FROM messages WHERE owner_id=? AND chat_id=? AND message_id=?",
            (owner_id, chat_id, message_id))

    async def cleanup(self, older_than: int) -> None:
        await self.run("DELETE FROM messages WHERE date < ?", (older_than,))

    # ---- события --------------------------------------------------------
    async def add_event(self, owner_id: int, kind: str, ts: int, label: str, html: str,
                        media_type: Optional[str] = None, file_id: Optional[str] = None,
                        ref: Optional[str] = None) -> int:
        return await self.run(
            """INSERT INTO events(owner_id, kind, ts, label, html, media_type, file_id, ref)
               VALUES (?,?,?,?,?,?,?,?)""",
            (owner_id, kind, ts, label, html, media_type, file_id, ref))

    async def count_events(self, owner_id: int, kind: Optional[str] = None) -> int:
        if kind:
            row = await self.run(
                "SELECT COUNT(*) AS n FROM events WHERE owner_id=? AND kind=?",
                (owner_id, kind), "one")
        else:
            row = await self.run(
                "SELECT COUNT(*) AS n FROM events WHERE owner_id=?", (owner_id,), "one")
        return int(row["n"]) if row else 0

    async def list_events(self, owner_id: int, limit: int, offset: int) -> list[Row]:
        return await self.run(
            "SELECT * FROM events WHERE owner_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (owner_id, limit, offset), "all")

    async def get_event(self, owner_id: int, event_id: int) -> Optional[Row]:
        return await self.run(
            "SELECT * FROM events WHERE owner_id=? AND id=?", (owner_id, event_id), "one")

    async def has_event_ref(self, owner_id: int, ref: str) -> bool:
        row = await self.run(
            "SELECT 1 AS x FROM events WHERE owner_id=? AND ref=? LIMIT 1", (owner_id, ref), "one")
        return row is not None

    # ---- mute -----------------------------------------------------------
    async def is_muted(self, owner_id: int, chat_id: int) -> bool:
        row = await self.run(
            "SELECT 1 AS x FROM muted WHERE owner_id=? AND chat_id=?", (owner_id, chat_id), "one")
        return row is not None

    async def toggle_mute(self, owner_id: int, chat_id: int) -> bool:
        """Возвращает новое состояние: True - режим игнора включён."""
        if await self.is_muted(owner_id, chat_id):
            await self.run("DELETE FROM muted WHERE owner_id=? AND chat_id=?", (owner_id, chat_id))
            return False
        await self.run("INSERT INTO muted(owner_id, chat_id) VALUES (?,?)", (owner_id, chat_id))
        return True

