#!/usr/bin/env python3
"""Polls a Discord channel for tuning embeds and stores one row per service in data/sac.db,
mirroring new rows to a Firebase Realtime Database for the shared dashboard.

Env: DISCORD_TOKEN, DISCORD_CHANNEL_ID, optional POLL_SECONDS (default 60).
Firebase (optional, needs all four): FIREBASE_API_KEY, FIREBASE_DB_URL, FIREBASE_EMAIL, FIREBASE_PASSWORD.
Rows are unique on (message_id, n) where n is the line's position in the bill, so
re-reading history never duplicates but a bill listing the same service twice keeps both.
"""
import json, os, re, sqlite3, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "sac.db")
TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL = os.environ["DISCORD_CHANNEL_ID"]
POLL = int(os.environ.get("POLL_SECONDS", "60"))
FB = {k: os.environ.get("FIREBASE_" + k) for k in ("API_KEY", "DB_URL", "EMAIL", "PASSWORD")}
# Start point when the database has no saved cursor (Discord snowflake for 2026-01-01 UTC).
CUTOFF = str((int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000) - 1420070400000) << 22)
COLS = "ts, player, vehicle, service, price, mechanic, message_id, n"

SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
  ts TEXT NOT NULL, player TEXT, vehicle TEXT, service TEXT, price INTEGER, mechanic TEXT,
  message_id TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, synced INTEGER NOT NULL DEFAULT 0,
  UNIQUE (message_id, n));
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


def http(url, body=None, method=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "sac-collector/1", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch(after):
    url = f"https://discord.com/api/v10/channels/{CHANNEL}/messages?limit=100&after={after}"
    for attempt in range(8):
        try:
            return http(url, headers={"Authorization": f"Bot {TOKEN}"})
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            wait = float(e.headers.get("Retry-After", 2 ** attempt))
            print(f"rate limited, sleeping {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError("gave up after repeated 429s")


def clean(s):
    return s.replace("*", "").strip()


def parse(message):
    """One row per tuning-list line: (ts, player, vehicle, service, price, mechanic, message_id, n)."""
    if not message.get("embeds"):
        return []
    embed = message["embeds"][0]
    is_bill = "Tuning Bill" in (embed.get("title") or "")
    ts = datetime.fromisoformat(message["timestamp"]).astimezone(timezone.utc)
    ts = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    player = vehicle = mechanic = ""
    in_list, rows = False, []
    for line in (embed.get("description") or "").split("\n"):
        line = line.strip()
        if line.startswith("Player"):
            if m := re.search(r"Player\s+([^\[]+)", line):
                player = clean(m.group(1))
            if m := re.search(r"vehicle\s+(.+?\(.*?\))", line, re.I):
                vehicle = clean(m.group(1))
            if not is_bill:
                mechanic = player
        if is_bill and (m := re.search(r"Mechanic\s+([^\[]+)", line)):
            mechanic = clean(m.group(1))
        if "Tuning List:" in line:
            in_list = True
            continue
        if in_list and (line.startswith("Discount") or re.match(r"^\d+:", line)):
            break
        if in_list and (m := re.match(r"^(.*?)\s*\$([\d,]+)", line)):
            service = re.sub(r"^[\s\-–—]+", "", clean(m.group(1)))
            rows.append((ts, player, vehicle, service, int(m.group(2).replace(",", "")), mechanic, message["id"], len(rows)))
    return rows


class Firebase:
    """Signs in as the collector user and mirrors rows under /logs, keyed so keys sort by time."""

    def __init__(self):
        self.token, self.expires = None, 0.0

    def auth(self):
        if time.time() > self.expires - 120:
            d = http(f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB['API_KEY']}",
                     {"email": FB["EMAIL"], "password": FB["PASSWORD"], "returnSecureToken": True})
            self.token, self.expires = d["idToken"], time.time() + int(d["expiresIn"])
        return self.token

    def sync(self, con):
        while True:
            rows = con.execute(f"SELECT {COLS} FROM logs WHERE synced=0 ORDER BY ts, message_id, n LIMIT 2000").fetchall()
            if not rows:
                return
            body = {f"{r[0].replace('.', '-')}_{r[6]}_{r[7]}": list(r[:6]) for r in rows}
            http(f"{FB['DB_URL']}/logs.json?auth={self.auth()}", body, method="PATCH")
            with con:
                con.executemany("UPDATE logs SET synced=1 WHERE message_id=? AND n=?", [(r[6], r[7]) for r in rows])
            print(f"synced {len(rows)} rows to Firebase", flush=True)


def main():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    if "synced" not in [c[1] for c in con.execute("PRAGMA table_info(logs)")]:
        con.execute("ALTER TABLE logs ADD COLUMN synced INTEGER NOT NULL DEFAULT 0")
    row = con.execute("SELECT value FROM state WHERE key='cursor'").fetchone()
    cursor = row[0] if row else CUTOFF
    fb = Firebase() if all(FB.values()) else None
    print(f"starting after {cursor}; firebase {'on' if fb else 'off'}", flush=True)
    while True:
        while True:
            msgs = sorted(fetch(cursor), key=lambda m: int(m["id"]))
            if not msgs:
                break
            rows = [r for m in msgs for r in parse(m)]
            with con:
                n = con.executemany(f"INSERT OR IGNORE INTO logs ({COLS}) VALUES (?,?,?,?,?,?,?,?)", rows).rowcount
                cursor = msgs[-1]["id"]
                con.execute("INSERT OR REPLACE INTO state VALUES ('cursor', ?)", (cursor,))
            if n:
                print(f"{len(msgs)} messages -> {n} new rows (cursor {cursor})", flush=True)
            if len(msgs) < 100:
                break
            time.sleep(1)
        if fb:
            try:
                fb.sync(con)
            except Exception as e:  # keep collecting even if Firebase is unreachable; rows stay synced=0
                print(f"firebase sync failed: {e}", flush=True)
        if "--once" in sys.argv:
            return
        time.sleep(POLL)


if __name__ == "__main__":
    main()
