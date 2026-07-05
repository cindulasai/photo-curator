from __future__ import annotations
import json, sqlite3
from pathlib import Path

_JSON_COLS = {"exif", "stage2", "stage3", "verdict_info"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS photos(
  rel_path TEXT PRIMARY KEY, kind TEXT, status TEXT DEFAULT 'ok',
  sha256 TEXT, size INTEGER, mtime REAL, width INTEGER, height INTEGER,
  ts REAL, ts_source TEXT, raw_sibling TEXT,
  exif TEXT, stage2 TEXT, stage3 TEXT,
  verdict TEXT, verdict_info TEXT, stage_done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS groups(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, champion TEXT, info TEXT);
CREATE TABLE IF NOT EXISTS group_members(
  group_id INTEGER, rel_path TEXT, PRIMARY KEY(group_id, rel_path));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
  start_ts REAL, end_ts REAL, significance INTEGER);
CREATE TABLE IF NOT EXISTS event_members(
  event_id INTEGER, rel_path TEXT, PRIMARY KEY(event_id, rel_path));
"""


class Store:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def set_meta(self, key: str, value: str):
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))
        self.conn.commit()

    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    @staticmethod
    def _enc(fields: dict) -> dict:
        return {k: (json.dumps(v, sort_keys=True) if k in _JSON_COLS and v is not None
                    else v)
                for k, v in fields.items()}

    @staticmethod
    def _dec(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in _JSON_COLS:
            if d.get(k):
                d[k] = json.loads(d[k])
        return d

    def upsert_photo(self, rel_path: str, **fields):
        f = self._enc(fields)
        cols = ["rel_path"] + list(f)
        sql = (f"INSERT INTO photos({','.join(cols)}) VALUES({','.join('?'*len(cols))}) "
               f"ON CONFLICT(rel_path) DO UPDATE SET "
               + ",".join(f"{c}=excluded.{c}" for c in f))
        self.conn.execute(sql, [rel_path] + list(f.values()))
        self.conn.commit()

    def update(self, rel_path: str, **fields):
        f = self._enc(fields)
        self.conn.execute(
            f"UPDATE photos SET {','.join(c + '=?' for c in f)} WHERE rel_path=?",
            list(f.values()) + [rel_path])
        self.conn.commit()

    def photo(self, rel_path: str):
        row = self.conn.execute("SELECT * FROM photos WHERE rel_path=?", (rel_path,)).fetchone()
        return self._dec(row) if row else None

    def photos(self, **eq) -> list[dict]:
        sql, args = "SELECT * FROM photos", []
        if eq:
            sql += " WHERE " + " AND ".join(f"{k}=?" for k in eq)
            args = list(eq.values())
        sql += " ORDER BY rel_path"
        return [self._dec(r) for r in self.conn.execute(sql, args)]

    def add_group(self, kind: str, members: list[str]) -> int:
        cur = self.conn.execute("INSERT INTO groups(kind) VALUES(?)", (kind,))
        gid = cur.lastrowid
        self.conn.executemany("INSERT INTO group_members VALUES(?,?)",
                              [(gid, m) for m in sorted(members)])
        self.conn.commit()
        return gid

    def set_group(self, gid: int, champion=None, info=None):
        if champion is not None:
            self.conn.execute("UPDATE groups SET champion=? WHERE id=?", (champion, gid))
        if info is not None:
            self.conn.execute("UPDATE groups SET info=? WHERE id=?",
                              (json.dumps(info, sort_keys=True), gid))
        self.conn.commit()

    def groups(self) -> list[dict]:
        out = []
        for g in self.conn.execute("SELECT * FROM groups ORDER BY id"):
            members = [r["rel_path"] for r in self.conn.execute(
                "SELECT rel_path FROM group_members WHERE group_id=? ORDER BY rel_path",
                (g["id"],))]
            out.append({"id": g["id"], "kind": g["kind"], "champion": g["champion"],
                        "info": json.loads(g["info"]) if g["info"] else None,
                        "members": members})
        return out

    def clear_events(self):
        self.conn.execute("DELETE FROM events")
        self.conn.execute("DELETE FROM event_members")
        self.conn.commit()

    def add_event(self, name, start_ts, end_ts, significance, members) -> int:
        cur = self.conn.execute(
            "INSERT INTO events(name,start_ts,end_ts,significance) VALUES(?,?,?,?)",
            (name, start_ts, end_ts, significance))
        eid = cur.lastrowid
        self.conn.executemany("INSERT INTO event_members VALUES(?,?)",
                              [(eid, m) for m in sorted(members)])
        self.conn.commit()
        return eid

    def events(self) -> list[dict]:
        out = []
        for e in self.conn.execute("SELECT * FROM events ORDER BY start_ts, id"):
            members = [r["rel_path"] for r in self.conn.execute(
                "SELECT rel_path FROM event_members WHERE event_id=? ORDER BY rel_path",
                (e["id"],))]
            out.append(dict(e) | {"members": members})
        return out
