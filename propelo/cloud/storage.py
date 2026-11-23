"""Where uploaded files live: a private local directory (the default), or the database
(STORAGE=db) for a server that has no disk of its own, such as a free instance whose
files vanish at every restart. The interface is small so an encrypted object store
(S3, GCS, R2) can replace either without touching the API."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

_KEY = re.compile(r"^[a-f0-9]{32}/[a-f0-9]{32}\.[a-z0-9]{1,8}$")


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def _path(self, key: str) -> Path:
        if not _KEY.match(key):
            raise ValueError("bad storage key")
        return self.root / key

    def put(self, user_id: str, asset_id: str, ext: str, data: bytes, conn=None) -> str:
        key = f"{user_id}/{asset_id}.{ext}"
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def delete_user(self, user_id: str) -> None:
        if re.fullmatch(r"[a-f0-9]{32}", user_id):
            shutil.rmtree(self.root / user_id, ignore_errors=True)


class DbStorage:
    """The same interface, with the bytes in the `blobs` table. Uploads are small (resumes, a few MB each,
    capped per person), so they sit comfortably beside the rest of the data and are covered by its backups."""

    def __init__(self, db):
        self.db = db

    def put(self, user_id: str, asset_id: str, ext: str, data: bytes, conn=None) -> str:
        """Pass the caller's open transaction as `conn` so the file and its listing are saved together."""
        key = f"{user_id}/{asset_id}.{ext}"
        if not _KEY.match(key):
            raise ValueError("bad storage key")
        from .db import now_iso

        def write(c):
            c.execute("DELETE FROM blobs WHERE key = ?", (key,))
            c.execute("INSERT INTO blobs(key, user_id, data, created_at) VALUES (?, ?, ?, ?)", (key, user_id, bytes(data), now_iso()))
        if conn is not None:
            write(conn)
        else:
            with self.db.tx() as c:
                write(c)
        return key

    def get(self, key: str) -> bytes:
        if not _KEY.match(key):
            raise ValueError("bad storage key")
        with self.db.tx() as c:
            row = c.one("SELECT data FROM blobs WHERE key = ?", (key,))
        if row is None:
            raise FileNotFoundError(key)
        return bytes(row["data"])

    def delete(self, key: str) -> None:
        if _KEY.match(key):
            with self.db.tx() as c:
                c.execute("DELETE FROM blobs WHERE key = ?", (key,))

    def delete_user(self, user_id: str) -> None:
        if re.fullmatch(r"[a-f0-9]{32}", user_id):
            with self.db.tx() as c:
                c.execute("DELETE FROM blobs WHERE user_id = ?", (user_id,))


def make_storage(cfg, db):
    return DbStorage(db) if cfg.storage == "db" else LocalStorage(cfg.upload_dir)
