"""翻译缓存：SQLite 存 (原文+语向+后端) -> 译文，重复句子零延迟。"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

from ..core.config import CACHE_DB


class Cache:
    def __init__(self, path: Path = CACHE_DB) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS tr ("
            "k TEXT PRIMARY KEY, src TEXT, dst TEXT, kind TEXT, ts REAL)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON tr(ts)")
        self._conn.commit()

    @staticmethod
    def _key(text: str, src: str, dst: str, backend: str) -> str:
        h = hashlib.sha1(f"{backend}|{src}|{dst}|{text}".encode("utf-8")).hexdigest()
        return h

    def get(self, text: str, src: str, dst: str, backend: str) -> str | None:
        k = self._key(text, src, dst, backend)
        with self._lock:
            row = self._conn.execute("SELECT dst FROM tr WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def put(self, text: str, src: str, dst: str, backend: str, result: str, kind: str = "nmt") -> None:
        import time
        k = self._key(text, src, dst, backend)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO tr (k, src, dst, kind, ts) VALUES (?,?,?,?,?)",
                (k, text, result, kind, time.time()),
            )
            self._conn.commit()

    def history(self, limit: int = 50) -> list[tuple[str, str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT src, dst, kind FROM tr ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return rows

    def clear(self) -> int:
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM tr").fetchone()[0]
            self._conn.execute("DELETE FROM tr")
            self._conn.commit()
        return int(n)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
