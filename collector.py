#!/usr/bin/env python3
"""Polls Discord log channels into data/sac.db and mirrors new rows to a Firebase Realtime Database.

Sources: tuning bills (#shop-logs -> table logs) and garage movements (#garage-logs -> table garage).
Env: DISCORD_TOKEN, DISCORD_CHANNEL_ID, DISCORD_GARAGE_CHANNEL_ID, optional POLL_SECONDS (default 60).
Firebase (optional, needs all four): FIREBASE_API_KEY, FIREBASE_DB_URL, FIREBASE_EMAIL, FIREBASE_PASSWORD.
Rows carry their Discord message id (plus line position for bills) and are unique on it, so
re-reading history never duplicates; Firebase keys start with the timestamp so they sort by time.
"""
import json, os, re, sqlite3, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "sac.db")
TOKEN = os.environ["DISCORD_TOKEN"]
POLL = int(os.environ.get("POLL_SECONDS", "60"))
FB = {k: os.environ.get("FIREBASE_" + k) for k in ("API_KEY", "DB_URL", "EMAIL", "PASSWORD")}
# Start point when a source has no saved cursor (Discord snowflake for 2026-01-01 UTC).
CUTOFF = str((int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000) - 1420070400000) << 22)

SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
  ts TEXT NOT NULL, player TEXT, vehicle TEXT, service TEXT, price INTEGER, mechanic TEXT,
  message_id TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, synced INTEGER NOT NULL DEFAULT 0,
  UNIQUE (message_id, n));
CREATE TABLE IF NOT EXISTS garage (
  ts TEXT NOT NULL, event TEXT NOT NULL, player TEXT, plate TEXT, vehicle TEXT, garage TEXT,
  message_id TEXT NOT NULL UNIQUE, synced INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
UPDATE state SET key='cursor:logs' WHERE key='cursor';
"""


def http(url, body=None, method=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "sac-collector/1", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch(channel, after):
    url = f"https://discord.com/api/v10/channels/{channel}/messages?limit=100&after={after}"
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


def iso(discord_ts):
    return datetime.fromisoformat(discord_ts).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def clean(s):
    return s.replace("*", "").strip()


def parse_bill(message):
    """One row per tuning-list line: (ts, player, vehicle, service, price, mechanic, message_id, n)."""
    if not message.get("embeds"):
        return []
    embed = message["embeds"][0]
    is_bill = "Tuning Bill" in (embed.get("title") or "")
    ts, player = iso(message["timestamp"]), ""
    vehicle = mechanic = ""
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


def parse_garage(message):
    """One row per 'Vehicle taken out' / 'Vehicle stored' embed: (ts, event, player, plate, vehicle, garage, message_id)."""
    if not message.get("embeds"):
        return []
    embed = message["embeds"][0]
    title = (embed.get("title") or "").lower()
    event = "out" if "taken out" in title else "in" if "stored" in title else None
    if not event:
        return []
    f = {x["name"]: x["value"] for x in embed.get("fields", [])}
    player = re.sub(r"\s*\(char\d+:[0-9a-f]+\)\s*$", "", f.get("Player", "")).strip()
    return [(iso(message["timestamp"]), event, player, f.get("Plate", ""), f.get("Vehicle", ""), f.get("Garage", ""), message["id"])]


SOURCES = [
    dict(name="logs", channel=os.environ.get("DISCORD_CHANNEL_ID"), parse=parse_bill,
         cols="ts, player, vehicle, service, price, mechanic, message_id, n", key=lambda r: f"{r[0].replace('.', '-')}_{r[6]}_{r[7]}"),
    dict(name="garage", channel=os.environ.get("DISCORD_GARAGE_CHANNEL_ID"), parse=parse_garage,
         cols="ts, event, player, plate, vehicle, garage, message_id", key=lambda r: f"{r[0].replace('.', '-')}_{r[6]}"),
]


class Firebase:
    """Signs in as the collector user and mirrors each table under /<name>; values are the first six columns."""

    def __init__(self):
        self.token, self.expires = None, 0.0

    def auth(self):
        if time.time() > self.expires - 120:
            d = http(f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB['API_KEY']}",
                     {"email": FB["EMAIL"], "password": FB["PASSWORD"], "returnSecureToken": True})
            self.token, self.expires = d["idToken"], time.time() + int(d["expiresIn"])
        return self.token

    def sync(self, con, src):
        while True:
            rows = con.execute(f"SELECT rowid, {src['cols']} FROM {src['name']} WHERE synced=0 ORDER BY ts LIMIT 2000").fetchall()
            if not rows:
                return
            http(f"{FB['DB_URL']}/{src['name']}.json?auth={self.auth()}", {src["key"](r[1:]): list(r[1:7]) for r in rows}, method="PATCH")
            with con:
                con.executemany(f"UPDATE {src['name']} SET synced=1 WHERE rowid=?", [(r[0],) for r in rows])
            print(f"synced {len(rows)} {src['name']} rows to Firebase", flush=True)


def poll(con, src):
    """Fetch every message after the saved cursor for this source and store the parsed rows."""
    key = f"cursor:{src['name']}"
    row = con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    cursor = row[0] if row else CUTOFF
    while True:
        msgs = sorted(fetch(src["channel"], cursor), key=lambda m: int(m["id"]))
        if not msgs:
            return
        rows = [r for m in msgs for r in src["parse"](m)]
        marks = ",".join("?" * len(src["cols"].split(",")))
        with con:
            n = con.executemany(f"INSERT OR IGNORE INTO {src['name']} ({src['cols']}) VALUES ({marks})", rows).rowcount
            cursor = msgs[-1]["id"]
            con.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, cursor))
        if n:
            print(f"{src['name']}: {len(msgs)} messages -> {n} new rows (cursor {cursor})", flush=True)
        if len(msgs) < 100:
            return
        time.sleep(1)


def main():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    sources = [s for s in SOURCES if s["channel"]]
    fb = Firebase() if all(FB.values()) else None
    print(f"sources: {[s['name'] for s in sources]}; firebase {'on' if fb else 'off'}", flush=True)
    while True:
        for src in sources:
            poll(con, src)
            if fb:
                try:
                    fb.sync(con, src)
                except Exception as e:  # keep collecting even if Firebase is unreachable; rows stay synced=0
                    print(f"firebase sync failed for {src['name']}: {e}", flush=True)
        if "--once" in sys.argv:
            return
        time.sleep(POLL)


if __name__ == "__main__":
    main()
