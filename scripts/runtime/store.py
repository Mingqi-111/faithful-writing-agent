"""Single-process transactions serialized by SQLite, stored outside the skill."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(self.directory / "state.sqlite3", timeout=20)
        self.connection.execute("PRAGMA foreign_keys = ON")
        # DELETE mode keeps committed state in one portable file after the CLI exits.
        self.connection.execute("PRAGMA journal_mode = DELETE")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
                user_id TEXT NOT NULL, scene TEXT NOT NULL,
                created_at TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS records_scope ON records(kind, user_id, scene);
            CREATE TABLE IF NOT EXISTS profiles (
                user_id TEXT NOT NULL, scene TEXT NOT NULL, active TEXT,
                history TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(user_id, scene)
            );
        """)
        self.connection.execute("BEGIN IMMEDIATE")

    def finish(self, success: bool = True):
        self.connection.commit() if success else self.connection.rollback()
        self.connection.close()

    def save(self, kind: str, user_id: str, scene: str, values: dict) -> dict:
        row = dict(values, id=f"{kind}_{uuid.uuid4().hex[:20]}", user_id=user_id,
                   scene=scene, created_at=datetime.now(timezone.utc).isoformat())
        self.connection.execute(
            "INSERT INTO records(id,kind,user_id,scene,created_at,data) VALUES(?,?,?,?,?,?)",
            (row["id"], kind, user_id, scene, row["created_at"], json.dumps(row, ensure_ascii=False)))
        return row

    def get(self, record_id: str, kind: str, user_id: str | None = None) -> dict:
        row = self.connection.execute("SELECT user_id,data FROM records WHERE id=? AND kind=?",
                                      (record_id, kind)).fetchone()
        if row is None or user_id is not None and row[0] != user_id:
            raise ValueError("记录不存在，或不属于这个用户")
        return json.loads(row[1])

    def update(self, row: dict, kind: str):
        result = self.connection.execute(
            "UPDATE records SET data=? WHERE id=? AND kind=? AND user_id=? AND scene=?",
            (json.dumps(row, ensure_ascii=False), row["id"], kind, row["user_id"], row["scene"]))
        if result.rowcount != 1:
            raise ValueError("记录更新失败")

    def list(self, kind: str, user_id: str, scene: str | None = None) -> list[dict]:
        sql = "SELECT data FROM records WHERE kind=? AND user_id=?"
        args = [kind, user_id]
        if scene is not None:
            sql += " AND scene=?"
            args.append(scene)
        return [json.loads(row[0]) for row in self.connection.execute(sql + " ORDER BY sequence", args)]

    def profile_state(self, user_id: str, scene: str) -> dict:
        row = self.connection.execute("SELECT active,history FROM profiles WHERE user_id=? AND scene=?",
                                      (user_id, scene)).fetchone()
        return {"active": row[0], "history": json.loads(row[1])} if row else {"active": None, "history": []}

    def set_profile(self, user_id: str, scene: str, active: str | None, history: list):
        self.connection.execute("""INSERT INTO profiles(user_id,scene,active,history) VALUES(?,?,?,?)
            ON CONFLICT(user_id,scene) DO UPDATE SET active=excluded.active,history=excluded.history""",
            (user_id, scene, active, json.dumps(history)))

    def active(self, user_id: str, scene: str) -> dict | None:
        active_id = self.profile_state(user_id, scene)["active"]
        return self.get(active_id, "candidate", user_id) if active_id else None
