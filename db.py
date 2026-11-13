"""SQLite storage for the Sunset Canyon helper. Pure standard library.

Existing databases are upgraded in place (columns are only ever added), so battles you
logged with an earlier version are kept.
"""
import os
import sqlite3

DB_PATH = os.environ.get("ROK_DB", "rok_canyon.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS commanders (
    name  TEXT PRIMARY KEY,
    troop TEXT DEFAULT '',          -- infantry / cavalry / archer / '' (unknown or mixed)
    role  TEXT DEFAULT 'any',       -- tank / back / any
    grade TEXT DEFAULT '',          -- canyon grade: S+, S, A+, A, B+, B, C or ''
    note  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS roster (
    name   TEXT PRIMARY KEY REFERENCES commanders(name),
    level  INTEGER DEFAULT 1,
    skills TEXT DEFAULT '',         -- e.g. 5511
    gear   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS battles (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT DEFAULT CURRENT_TIMESTAMP,
    mode    TEXT DEFAULT 'sunset',
    my_side TEXT DEFAULT 'attack',  -- attack / defend
    result  TEXT CHECK (result IN ('win','loss','draw')),
    note    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS marches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id     INTEGER REFERENCES battles(id) ON DELETE CASCADE,
    team          TEXT CHECK (team IN ('mine','enemy')),
    slot          INTEGER,
    lane          TEXT CHECK (lane IN ('front','back')),
    primary_cmd   TEXT,
    secondary_cmd TEXT DEFAULT '',
    troop         TEXT DEFAULT '',
    level         INTEGER,
    skills        TEXT DEFAULT '',
    gear          TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_marches_battle ON marches(battle_id);
CREATE TABLE IF NOT EXISTS scouted (       -- line-ups seen on the challenge list, fought or not
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT DEFAULT CURRENT_TIMESTAMP,
    mode    TEXT,
    key     TEXT UNIQUE,                   -- the five primary commanders: one row per opponent line-up
    lineup  TEXT                           -- JSON: [[primary, secondary, level, expertised], ...]
);
CREATE TABLE IF NOT EXISTS pairings (      -- primary + secondary combinations recommended by guides
    primary_cmd   TEXT,
    secondary_cmd TEXT,
    note          TEXT DEFAULT '',
    PRIMARY KEY (primary_cmd, secondary_cmd)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Columns added after version 1. (table, column, definition)
ADDED = [
    ("battles", "source", "TEXT DEFAULT 'manual'"),   # manual / auto
    ("battles", "needs_review", "INTEGER DEFAULT 0"),
    ("battles", "opp_name", "TEXT DEFAULT ''"),
    ("battles", "opp_power", "INTEGER"),
    ("battles", "my_power", "INTEGER"),
    ("battles", "rank_before", "INTEGER"),
    ("battles", "rank_after", "INTEGER"),
    ("battles", "stars_delta", "INTEGER"),
    ("battles", "opp_stars_delta", "INTEGER"),
    ("battles", "shot", "TEXT DEFAULT ''"),           # saved pre-battle screenshot
    ("roster", "stars", "INTEGER"),
    ("roster", "power", "INTEGER"),
    ("roster", "capacity", "INTEGER"),
    ("roster", "updated", "TEXT DEFAULT ''"),          # when the commander screen was last read
    ("marches", "col", "INTEGER"),                    # 0 = column nearest the enemy, 1 = behind it
    ("marches", "row", "INTEGER"),                    # 0 = top row of the grid
    ("marches", "troops", "INTEGER"),
    ("marches", "remaining", "INTEGER"),              # from the stats screen
    ("marches", "kills", "INTEGER"),
    ("marches", "healed", "INTEGER"),
    ("marches", "conf", "REAL"),
    ("marches", "expert", "INTEGER"),                 # enemy main commander expertised (from scouting)
]

BATTLE_EXTRA = ("source", "needs_review", "opp_name", "opp_power", "my_power",
                "rank_before", "rank_after", "stars_delta", "opp_stars_delta", "shot")
MARCH_KEYS = ("team", "slot", "lane", "primary_cmd", "secondary_cmd", "troop", "level",
              "skills", "gear", "col", "row", "troops", "remaining", "kills", "healed", "conf")


def _migrate(conn):
    for table, col, definition in ADDED:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
    # skills and gear rarities read from the main commander view were unreliable: clear them once
    if not conn.execute("SELECT 1 FROM settings WHERE key='cleared_small_reads'").fetchone():
        conn.execute("UPDATE roster SET skills='', gear=''")
        conn.execute("INSERT INTO settings(key, value) VALUES ('cleared_small_reads', '1')")
    # Lost Canyon results show no rank or star change; early versions saved them as 'sunset'
    conn.execute("UPDATE battles SET mode='lost' WHERE mode='sunset' AND source='auto' "
                 "AND rank_before IS NULL AND stars_delta IS NULL")
    clear_bad_secondaries(conn)
    conn.commit()


def clear_bad_secondaries(conn):
    """A commander serves once per line-up: a secondary that is also a primary on the same side,
    or that appears twice as a secondary, is a misread face. Which copy is right cannot be told,
    so every impossible one is cleared (wrong data is worse than none)."""
    conn.execute(
        "UPDATE marches SET secondary_cmd='' WHERE secondary_cmd<>'' AND (secondary_cmd=primary_cmd OR EXISTS (SELECT 1 FROM marches o "
        "WHERE o.battle_id=marches.battle_id AND o.team=marches.team AND o.id<>marches.id "
        "AND (o.primary_cmd=marches.secondary_cmd OR o.secondary_cmd=marches.secondary_cmd)))")


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def get_setting(conn, key, default=""):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r and r["value"] is not None else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()


def ensure_commander(conn, name):
    name = (name or "").strip()
    if name:
        conn.execute("INSERT OR IGNORE INTO commanders(name) VALUES (?)", (name,))
    return name


def _insert_march(conn, bid, m):
    ensure_commander(conn, m["primary_cmd"])
    ensure_commander(conn, m.get("secondary_cmd", ""))
    vals = {k: m.get(k) for k in MARCH_KEYS}
    vals["secondary_cmd"] = vals["secondary_cmd"] or ""
    vals["troop"] = vals["troop"] or ""
    vals["skills"] = vals["skills"] or ""
    vals["gear"] = vals["gear"] or ""
    cols = ",".join(MARCH_KEYS)
    qs = ",".join("?" for _ in MARCH_KEYS)
    conn.execute(f"INSERT INTO marches(battle_id,{cols}) VALUES (?,{qs})",
                 (bid, *[vals[k] for k in MARCH_KEYS]))


def save_battle(conn, my_side, result, note, marches, mode="sunset", **extra):
    """marches: list of dicts (see MARCH_KEYS; only team, slot, lane, primary_cmd are required).
    extra: any of BATTLE_EXTRA."""
    cur = conn.execute(
        "INSERT INTO battles(mode, my_side, result, note) VALUES (?,?,?,?)",
        (mode, my_side, result, note),
    )
    bid = cur.lastrowid
    sets = {k: v for k, v in extra.items() if k in BATTLE_EXTRA}
    if sets:
        conn.execute("UPDATE battles SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?",
                     (*sets.values(), bid))
    for m in marches:
        _insert_march(conn, bid, m)
    conn.commit()
    return bid


def replace_marches(conn, battle_id, marches):
    conn.execute("DELETE FROM marches WHERE battle_id=?", (battle_id,))
    for m in marches:
        _insert_march(conn, battle_id, m)
    conn.commit()


def update_battle_stats(conn, battle_id, side_rows):
    """side_rows: {'mine': [{name, secondary, remaining, healed, kills}], 'enemy': [...]}
    Matches rows to the saved marches by commander name and fills in the numbers."""
    n = 0
    for team, rows in side_rows.items():
        for r in rows:
            if not r.get("name"):
                continue
            cur = conn.execute(
                "UPDATE marches SET remaining=?, healed=?, kills=?, "
                "secondary_cmd=CASE WHEN ?<>'' THEN ? ELSE secondary_cmd END "
                "WHERE battle_id=? AND team=? AND primary_cmd=?",
                (r.get("remaining"), r.get("healed"), r.get("kills"),
                 r.get("secondary") or "", r.get("secondary") or "",
                 battle_id, team, r["name"]))
            n += cur.rowcount
            if r.get("secondary"):
                ensure_commander(conn, r["secondary"])
    clear_bad_secondaries(conn)
    conn.commit()
    return n


def sync_roster(conn):
    """Your roster is whoever you have fielded (main or secondary slot); nothing to type in."""
    # level 0 = not read from the commander screen yet (an earlier version guessed 60)
    conn.execute("UPDATE roster SET level=0 WHERE level=60 AND skills='' AND (gear='' OR gear IS NULL)")
    for col in ("primary_cmd", "secondary_cmd"):
        conn.execute(f"INSERT OR IGNORE INTO commanders(name) SELECT DISTINCT {col} FROM marches "
                     f"WHERE team='mine' AND {col}<>'' AND {col} NOT LIKE 'Unknown %'")
        conn.execute(f"INSERT OR IGNORE INTO roster(name, level) SELECT DISTINCT {col}, 0 FROM marches "
                     f"WHERE team='mine' AND {col}<>'' AND {col} NOT LIKE 'Unknown %'")
    conn.commit()


def log_scout(conn, mode, marches):
    """Remember a line-up seen on the challenge list (each distinct line-up once)."""
    import json
    lineup = json.dumps([[m["name"], m["secondary"], m["level"], bool(m.get("expert"))] for m in marches])
    key = json.dumps([m["name"] for m in marches])
    # a later, better read of the same opponent (a secondary recognised, a level corrected) replaces the row
    conn.execute("INSERT INTO scouted(mode, key, lineup) VALUES (?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET lineup=excluded.lineup", (mode, key, lineup))
    conn.commit()


def save_commander(conn, name, **fields):
    """Store facts read from one of the commander views. Only the fields given are changed:
    level, stars, power, capacity (main view), skills (SKILLS view), gear (stats popup, a dict)."""
    import json
    ensure_commander(conn, name)
    conn.execute("INSERT OR IGNORE INTO roster(name, level) VALUES (?, 0)", (name,))
    if "gear" in fields:
        fields["gear"] = json.dumps(fields["gear"])
    keep = {k: v for k, v in fields.items() if k in ("level", "stars", "power", "capacity", "skills", "gear") and v is not None}
    sets = ", ".join(f"{k}=?" for k in keep)
    conn.execute(f"UPDATE roster SET {sets + ', ' if sets else ''}updated=datetime('now', 'localtime') WHERE name=?",
                 (*keep.values(), name))
    conn.commit()


def fix_names(conn, known):
    """Rename commanders stored with an OCR slip (e.g. 'Matilda Of Flander') to the real name,
    everywhere they appear. Only near-certain matches (90% similar) are touched."""
    import difflib
    key = lambda s: s.lower().replace(" ", "")
    for (old,) in conn.execute("SELECT name FROM commanders").fetchall():
        if old in known:
            continue
        best = max(known, key=lambda k: difflib.SequenceMatcher(None, key(old), key(k)).ratio())
        if difflib.SequenceMatcher(None, key(old), key(best)).ratio() < 0.9:
            continue
        # the real name must exist before anything points at it (roster rows reference commanders)
        conn.execute("INSERT OR IGNORE INTO commanders(name, troop, role, grade, note) "
                     "SELECT ?, troop, role, grade, note FROM commanders WHERE name=?", (best, old))
        for col in ("primary_cmd", "secondary_cmd"):
            conn.execute(f"UPDATE marches SET {col}=? WHERE {col}=?", (best, old))
        conn.execute("UPDATE pairings SET primary_cmd=? WHERE primary_cmd=?", (best, old))
        conn.execute("UPDATE OR IGNORE pairings SET secondary_cmd=? WHERE secondary_cmd=?", (best, old))
        if conn.execute("SELECT 1 FROM roster WHERE name=?", (best,)).fetchone():
            conn.execute("DELETE FROM roster WHERE name=?", (old,))
        else:
            conn.execute("UPDATE roster SET name=? WHERE name=?", (best, old))
        conn.execute("DELETE FROM commanders WHERE name=?", (old,))
    # Joan of Arc was seeded as a back-line support; with Matilda she is a tank (user's correction)
    if not conn.execute("SELECT 1 FROM settings WHERE key='joan_tank'").fetchone():
        conn.execute("UPDATE commanders SET role='tank' WHERE name='Joan of Arc' AND role='back'")
        conn.execute("INSERT INTO settings(key, value) VALUES ('joan_tank', '1')")
    conn.commit()


def link_scout(conn, battle_id):
    """Copy what the challenge list showed about this opponent (levels, expertise, secondaries)
    into the fight's enemy marches, when a scouted line-up has the same five commanders."""
    import json
    names = {r[0] for r in conn.execute("SELECT primary_cmd FROM marches WHERE battle_id=? AND team='enemy'", (battle_id,))}
    for (lineup,) in conn.execute("SELECT lineup FROM scouted ORDER BY id DESC").fetchall():
        rows = json.loads(lineup)
        if {r[0] for r in rows if r[0]} != names:
            continue
        for name, sec, level, expert in rows:
            if name:
                conn.execute("UPDATE marches SET level=COALESCE(level, ?), expert=?, "
                             "secondary_cmd=CASE WHEN secondary_cmd='' AND ? IS NOT NULL THEN ? ELSE secondary_cmd END "
                             "WHERE battle_id=? AND team='enemy' AND primary_cmd=?",
                             (level, int(bool(expert)), sec, sec, battle_id, name))
        clear_bad_secondaries(conn)
        conn.commit()
        return True
    return False


def check_battle(conn, battle_id):
    """Plausibility checks on one saved fight; clears values that cannot be right and flags the
    fight for a look in History. -> list of problems found"""
    import statistics
    problems = []
    b = conn.execute("SELECT * FROM battles WHERE id=?", (battle_id,)).fetchone()
    mine_pw = [r[0] for r in conn.execute("SELECT my_power FROM battles WHERE my_power IS NOT NULL")]
    if b["my_power"] and len(mine_pw) >= 3 and not 0.8 < b["my_power"] / statistics.median(mine_pw) < 1.25:
        conn.execute("UPDATE battles SET my_power=NULL WHERE id=?", (battle_id,))       # a dropped digit
    b = conn.execute("SELECT * FROM battles WHERE id=?", (battle_id,)).fetchone()
    if b["opp_power"] and b["my_power"] and not 0.67 < b["opp_power"] / b["my_power"] < 1.5:
        conn.execute("UPDATE battles SET opp_power=NULL WHERE id=?", (battle_id,))
    for m in conn.execute("SELECT id, team, primary_cmd, troops FROM marches WHERE battle_id=? AND troops IS NOT NULL", (battle_id,)).fetchall():
        usual = [r[0] for r in conn.execute("SELECT troops FROM marches WHERE team=? AND primary_cmd=? AND troops>=20000 AND battle_id<>?",
                                            (m["team"], m["primary_cmd"], battle_id))]
        if m["troops"] < 20000 or (len(usual) >= 3 and m["troops"] < 0.5 * statistics.median(usual)):
            conn.execute("UPDATE marches SET troops=NULL WHERE id=?", (m["id"],))
            problems.append(f"troop count of {m['primary_cmd']} ({m['troops']:,}) was a misread and was cleared")
    for team, label in (("mine", "your"), ("enemy", "their")):
        n = conn.execute("SELECT COUNT(*) FROM marches WHERE battle_id=? AND team=?", (battle_id, team)).fetchone()[0]
        if n < 5:
            problems.append(f"only {n} of {label} marches were read (a game notification may have covered one): add it in edit")
    if problems:
        note = "check: " + "; ".join(problems)
        conn.execute("UPDATE battles SET needs_review=1, note=? WHERE id=? AND needs_review=0", (note, battle_id))
    conn.commit()
    return problems


def repair(conn):
    """Run the checks and the scouting link over fights saved by earlier versions (once)."""
    if conn.execute("SELECT 1 FROM settings WHERE key='repair_v1'").fetchone():
        return
    for (bid,) in conn.execute("SELECT id FROM battles ORDER BY id").fetchall():
        check_battle(conn, bid)
        link_scout(conn, bid)
    conn.execute("INSERT INTO settings(key, value) VALUES ('repair_v1', '1')")
    conn.commit()
