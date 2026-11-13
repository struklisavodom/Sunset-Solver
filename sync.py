"""Shares fights with friends through one free Supabase (Postgres) table. Standard library only.

Each player keeps their own rok_canyon.db. Every minute this module
  - uploads your finished fights (no player or opponent names: a random player id only),
  - downloads everyone else's into the local `shared_fights` table, which only pooled views read.

Connection details come from `shared.json` next to app.py: {"url": "https://xxxx.supabase.co", "key": "<anon key>"}.
Without that file nothing is sent anywhere. The table is created once with SCHEMA_SQL (Supabase > SQL editor).
"""
import calendar
import json
import os
import time
import urllib.request
import uuid

import db

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared.json")

SCHEMA_SQL = """create table if not exists fights (
  id         bigint generated always as identity primary key,
  player     text not null,
  local_id   integer not null,
  created_at timestamptz default now(),
  ts text, mode text, my_side text, result text,
  my_power bigint, opp_power bigint, stars_delta integer,
  marches    jsonb not null,
  unique (player, local_id)
);
alter table fights enable row level security;
create policy "anyone with the key reads" on fights for select using (true);
create policy "anyone with the key adds" on fights for insert with check (true);
"""
# No update or delete policy: a fight, once shared, cannot be changed or removed by any client.

MARCH_FIELDS = ("team", "primary_cmd", "secondary_cmd", "col", "row", "troops", "remaining", "kills", "healed", "level", "expert")
SETTLE = 30 * 60        # a fight is shared once its stats are in, or after this long (stats never came)

STATUS = {"state": "off", "last": "", "error": "", "pushed": 0, "pulled": 0}


def load_config(path=CONFIG):
    """-> {"url", "key"} or None. A secret / service-role key is refused: this file goes to friends, and that
    key bypasses the table's rules (anyone holding it could delete everything)."""
    try:
        with open(path, encoding="utf-8") as fh:
            c = json.load(fh)
    except (OSError, ValueError):
        return None
    key = (c.get("key") or "").strip()
    if not c.get("url") or not key.startswith(("sb_publishable_", "eyJ")):
        STATUS.update(error="shared.json needs the publishable key (sb_publishable_...), never the secret key"
                      if key.startswith("sb_secret_") else "")
        return None
    url = c["url"].strip()
    if "." not in url:                      # just the project ref was given
        url = f"https://{url}.supabase.co"
    return {"url": url, "key": key}


def player_id(conn):
    pid = db.get_setting(conn, "player_id")
    if not pid:
        pid = uuid.uuid4().hex[:12]
        db.set_setting(conn, "player_id", pid)
    return pid


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS shared_fights (
        id INTEGER PRIMARY KEY, player TEXT, local_id INTEGER, ts TEXT, mode TEXT, my_side TEXT, result TEXT,
        my_power INTEGER, opp_power INTEGER, stars_delta INTEGER, marches TEXT)""")
    conn.execute("CREATE TABLE IF NOT EXISTS shared_pushed (battle_id INTEGER PRIMARY KEY)")
    conn.commit()


def ready_fights(conn, now=None):
    """Your fights not shared yet whose data is final: stats read, or old enough that they never will be."""
    now = now or time.time()
    out = []
    for b in conn.execute("SELECT * FROM battles WHERE result IN ('win','loss','draw') "
                          "AND id NOT IN (SELECT battle_id FROM shared_pushed) ORDER BY id").fetchall():
        ms = conn.execute("SELECT * FROM marches WHERE battle_id=?", (b["id"],)).fetchall()
        stats = any(m["remaining"] is not None for m in ms)
        # battles.ts is SQLite's CURRENT_TIMESTAMP: UTC
        age = now - calendar.timegm(time.strptime(b["ts"][:19], "%Y-%m-%d %H:%M:%S")) if b["ts"] else SETTLE
        if not ms or not (stats or age >= SETTLE):
            continue
        out.append((b["id"], {
            "local_id": b["id"], "ts": b["ts"], "mode": b["mode"], "my_side": b["my_side"], "result": b["result"],
            "my_power": b["my_power"], "opp_power": b["opp_power"], "stars_delta": b["stars_delta"],
            "marches": [{k: m[k] for k in MARCH_FIELDS} for m in ms]}))
    return out


def _http(method, url, key, body=None):
    headers = {"apikey": key, "Content-Type": "application/json", "Prefer": "resolution=ignore-duplicates,return=minimal"}
    if key.startswith("eyJ"):               # legacy anon key is a JWT; the new sb_publishable_ keys go in apikey only
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    return json.loads(data) if data else None


def sync_once(conn, cfg, http=_http):
    """One round: push ready fights, pull new ones from others. -> (pushed, pulled)"""
    ensure_tables(conn)
    me = player_id(conn)
    base = cfg["url"].rstrip("/") + "/rest/v1/fights"
    ready = ready_fights(conn)
    if ready:
        http("POST", base + "?on_conflict=player,local_id", cfg["key"], [dict(f, player=me) for _, f in ready])
        conn.executemany("INSERT OR IGNORE INTO shared_pushed(battle_id) VALUES (?)", [(i,) for i, _ in ready])
        conn.commit()
    pulled = 0
    while True:
        last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM shared_fights").fetchone()[0]
        rows = http("GET", f"{base}?id=gt.{last}&order=id&limit=500", cfg["key"]) or []
        for r in rows:          # your own come back too: kept, so pooled views count everyone the same way
            conn.execute("INSERT OR IGNORE INTO shared_fights VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (r["id"], r["player"], r["local_id"], r["ts"], r["mode"], r["my_side"], r["result"],
                          r["my_power"], r["opp_power"], r["stars_delta"], json.dumps(r["marches"])))
        conn.commit()
        pulled += len(rows)
        if len(rows) < 500:
            break
    return len(ready), pulled


def run_forever(interval=60):
    """Background loop started by app.py; does nothing without shared.json."""
    while True:
        cfg = load_config()
        if not cfg:
            STATUS.update(state="off")
        else:
            conn = db.connect()
            try:
                pushed, pulled = sync_once(conn, cfg)
                STATUS.update(state="on", last=time.strftime("%H:%M"), error="",
                              pushed=STATUS["pushed"] + pushed, pulled=STATUS["pulled"] + pulled)
            except Exception as e:      # offline, wrong key...: try again next round
                STATUS.update(state="error", error=f"{type(e).__name__}: {e}")
            finally:
                conn.close()
        time.sleep(interval)


def pooled(conn):
    """Stats over everyone's shared fights. -> {"players", "fights", "won", "enemies": [(name, fights, win share)]}"""
    ensure_tables(conn)
    rows = conn.execute("SELECT player, result, marches FROM shared_fights WHERE my_side='attack'").fetchall()
    seen = {}
    for r in rows:
        for m in json.loads(r["marches"]):
            if m["team"] == "enemy" and m["primary_cmd"] and not m["primary_cmd"].startswith("Unknown"):
                d = seen.setdefault(m["primary_cmd"], [0, 0])
                d[0] += 1
                d[1] += r["result"] == "win"
    enemies = sorted(((n, k, w / k) for n, (k, w) in seen.items() if k >= 5), key=lambda t: t[2])
    return {"players": len({r["player"] for r in rows}), "fights": len(rows),
            "won": sum(r["result"] == "win" for r in rows), "enemies": enemies}
