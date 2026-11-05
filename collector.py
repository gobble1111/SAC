#!/usr/bin/env python3
"""Polls a Discord channel for tuning embeds and stores one row per service in data/sac.db.

Env: DISCORD_TOKEN, DISCORD_CHANNEL_ID, optional POLL_SECONDS (default 60).
Rows are unique on (message_id, n) where n is the line's position in the bill, so
re-reading history never duplicates but a bill listing the same service twice keeps both.
"""
import json, os, re, sqlite3, sys, time, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "sac.db")
TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL = os.environ["DISCORD_CHANNEL_ID"]
POLL = int(os.environ.get("POLL_SECONDS", "60"))
# Start point when the database has no saved cursor (Discord snowflake for 2026-01-01 UTC).
CUTOFF = str((int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000) - 1420070400000) << 22)

SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
  ts TEXT NOT NULL, player TEXT, vehicle TEXT, service TEXT, price INTEGER, mechanic TEXT,
  message_id TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, UNIQUE (message_id, n));
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


def fetch(after):
    url = f"https://discord.com/api/v10/channels/{CHANNEL}/messages?limit=100&after={after}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bot {TOKEN}", "User-Agent": "sac-collector/1"})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
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


def main():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    row = con.execute("SELECT value FROM state WHERE key='cursor'").fetchone()
    cursor = row[0] if row else CUTOFF
    print(f"starting after {cursor}", flush=True)
    while True:
        while True:
            msgs = sorted(fetch(cursor), key=lambda m: int(m["id"]))
            if not msgs:
                break
            rows = [r for m in msgs for r in parse(m)]
            with con:
                n = con.executemany("INSERT OR IGNORE INTO logs VALUES (?,?,?,?,?,?,?,?)", rows).rowcount
                cursor = msgs[-1]["id"]
                con.execute("INSERT OR REPLACE INTO state VALUES ('cursor', ?)", (cursor,))
            if n:
                print(f"{len(msgs)} messages -> {n} new rows (cursor {cursor})", flush=True)
            if len(msgs) < 100:
                break
            time.sleep(1)
        if "--once" in sys.argv:
            return
        time.sleep(POLL)


if __name__ == "__main__":
    main()
