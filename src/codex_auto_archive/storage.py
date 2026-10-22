from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import portalocker
from platformdirs import user_data_path
from pydantic import ValidationError

from .models import Config, Policy


def data_dir() -> Path:
    if value := os.environ.get("CODEX_AUTO_ARCHIVE_HOME"):
        return Path(value).expanduser().resolve()
    # Independent, stable scope per CODEX_HOME; never use plugin version cache paths.
    home = str(Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve())
    return (
        user_data_path("codex-auto-archive", appauthor=False)
        / hashlib.sha256(home.encode()).hexdigest()[:16]
    )


def atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Store:
    """Own configuration/state only. No access to Codex SQLite or rollout files."""

    def __init__(self, root: Path | None = None):
        self.root = root or data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "config.json"
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, thread_id TEXT, at REAL);
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY, at REAL, action TEXT, thread_id TEXT, result TEXT);
            CREATE INDEX IF NOT EXISTS history_time ON history(at);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / "state.sqlite3", timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def lock(self, name="scan", timeout=0):
        with portalocker.Lock(str(self.root / (name + ".lock")), timeout=timeout):
            yield

    def config(self) -> Config:
        with self.lock("config", 5):
            return self._load_config()

    def _load_config(self):
        if not self.config_path.exists():
            c = Config()
            atomic_write(self.config_path, c.model_dump(exclude_none=True))
            return c
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            # Migrate the flat v0 example format without enabling execution.
            if "schema_version" not in raw:
                policy_keys = Policy.model_fields.keys()
                policy = {k: raw.pop(k) for k in list(raw) if k in policy_keys}
                raw.update(schema_version=1, policy=policy, dry_run=True)
                c = Config.model_validate(raw)
                atomic_write(self.config_path, c.model_dump(exclude_none=True))
                return c
            return Config.model_validate(raw)
        except (ValueError, ValidationError) as e:
            # Preserve damaged input and fail closed instead of restoring executable settings.
            copy = self.root / f"config.corrupt-{time.time_ns()}.json"
            shutil.copyfile(self.config_path, copy)
            c = Config(enabled=False, dry_run=True)
            atomic_write(self.config_path, c.model_dump(exclude_none=True))
            self.audit("config_recovery", None, {"error": type(e).__name__, "backup": str(copy)})
            return c

    def edit(self, change):
        with self.lock("config", 5):
            c = self._load_config()
            change(c)
            c = Config.model_validate(c.model_dump(exclude_none=True))
            if self.config_path.exists():
                shutil.copyfile(self.config_path, self.root / "config.previous.json")
            atomic_write(self.config_path, c.model_dump(exclude_none=True))
            return c

    def get(self, key, default=None):
        with self.db() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    def activity(self, tid):
        return self.get("thread:" + tid, {})

    def mutate_activity(self, tid, fn):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            key = "thread:" + tid
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            data = json.loads(row[0]) if row else {}
            fn(data)
            db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(data)))
            return data

    def audit(self, action, tid, result):
        with self.db() as db:
            db.execute(
                "INSERT INTO history(at,action,thread_id,result) VALUES (?,?,?,?)",
                (time.time(), action, tid, json.dumps(result, ensure_ascii=False)),
            )

    def history(self, limit=10, since=0, action=None):
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM history WHERE at>=? AND (? IS NULL OR action=?) ORDER BY id DESC LIMIT ?",
                (since, action, action, limit),
            ).fetchall()
            return [{**dict(row), "result": json.loads(row["result"])} for row in rows]
