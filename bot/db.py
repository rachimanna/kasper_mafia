import logging
import time
from typing import List, Optional, Tuple

import aiosqlite

from bot.config import config

logger = logging.getLogger(__name__)


class StatsDB:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("DB is not initialized")
        return self._conn

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                won INTEGER NOT NULL,
                survived INTEGER NOT NULL,
                finished_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_results_user ON results(user_id);
            CREATE INDEX IF NOT EXISTS idx_results_chat ON results(chat_id);
            """
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def save_game(self, game_id: str, chat_id: int, rows: List[Tuple[int, str, str, bool, bool]]) -> None:
        now = int(time.time())
        await self.conn.executemany(
            "INSERT INTO results (game_id, chat_id, user_id, name, role, won, survived, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(game_id, chat_id, uid, name, role, int(won), int(survived), now) for uid, name, role, won, survived in rows],
        )
        await self.conn.commit()

    async def user_stats(self, user_id: int) -> Tuple[int, int, int, List[Tuple[str, int, int]]]:
        async with self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(won),0), COALESCE(SUM(survived),0) FROM results WHERE user_id = ?",
            (user_id,),
        ) as cur:
            games, wins, survived = await cur.fetchone()
        async with self.conn.execute(
            "SELECT role, COUNT(*), SUM(won) FROM results WHERE user_id = ? GROUP BY role ORDER BY COUNT(*) DESC",
            (user_id,),
        ) as cur:
            roles = await cur.fetchall()
        return games, wins, survived, roles

    async def top(self, chat_id: int, limit: int = 10) -> List[Tuple[str, int, int]]:
        async with self.conn.execute(
            """
            SELECT (SELECT name FROM results r2 WHERE r2.user_id = r.user_id ORDER BY id DESC LIMIT 1),
                   SUM(won), COUNT(*)
            FROM results r WHERE chat_id = ?
            GROUP BY user_id ORDER BY SUM(won) DESC, COUNT(*) ASC LIMIT ?
            """,
            (chat_id, limit),
        ) as cur:
            return await cur.fetchall()


db = StatsDB(config.DB_PATH)
