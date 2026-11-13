"""End-to-end check: the sample screenshots are fed to the watcher as if they were the live
screen. Also checks that a version-1 database upgrades without losing battles, and that
every page of the app loads.   Run:  python test_e2e.py"""
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
os.environ["ROK_DB"] = os.path.join(tmp, "test.db")

import db  # noqa: E402
import engine  # noqa: E402
import portraits  # noqa: E402
import priors  # noqa: E402
import watcher  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f"   expected {want!r}"))
    if not ok:
        fails.append(label)


shot = lambda n: Image.open(os.path.join(HERE, "testshots", n + ".png")).convert("RGB")

print("upgrade of a version-1 database")
old = sqlite3.connect(os.environ["ROK_DB"])
old.executescript("""
CREATE TABLE commanders (name TEXT PRIMARY KEY, troop TEXT DEFAULT '', role TEXT DEFAULT 'any', grade TEXT DEFAULT '', note TEXT DEFAULT '');
CREATE TABLE roster (name TEXT PRIMARY KEY REFERENCES commanders(name), level INTEGER DEFAULT 1, skills TEXT DEFAULT '', gear TEXT DEFAULT '');
CREATE TABLE battles (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, mode TEXT DEFAULT 'sunset', my_side TEXT DEFAULT 'attack', result TEXT CHECK (result IN ('win','loss','draw')), note TEXT DEFAULT '');
CREATE TABLE marches (id INTEGER PRIMARY KEY AUTOINCREMENT, battle_id INTEGER REFERENCES battles(id) ON DELETE CASCADE, team TEXT CHECK (team IN ('mine','enemy')), slot INTEGER, lane TEXT CHECK (lane IN ('front','back')), primary_cmd TEXT, secondary_cmd TEXT DEFAULT '', troop TEXT DEFAULT '', level INTEGER, skills TEXT DEFAULT '', gear TEXT DEFAULT '');
INSERT INTO commanders(name) VALUES ('Richard I');
INSERT INTO roster(name, level) VALUES ('Richard I', 40);
INSERT INTO battles(result) VALUES ('loss');
INSERT INTO marches(battle_id, team, slot, lane, primary_cmd) VALUES (1,'mine',1,'front','Richard I');
""")
old.commit()
old.close()
conn = db.connect()
priors.seed_commanders(conn)
check("old battle kept", conn.execute("SELECT result, source FROM battles WHERE id=1").fetchone()[:], ("loss", "manual"))
conn.execute("INSERT INTO battles(result, source) VALUES ('win', 'auto')")   # no rank, no stars
conn.commit(); conn.close(); conn = db.connect()
check("old Lost Canyon fight relabelled, hand-logged one untouched",
      [r[0] for r in conn.execute("SELECT mode FROM battles ORDER BY id")], ["sunset", "lost"])
conn.execute("DELETE FROM battles WHERE id=2"); conn.commit()
check("old march kept", conn.execute("SELECT primary_cmd, col FROM marches WHERE battle_id=1").fetchone()[:], ("Richard I", None))

print("watcher fed with the screenshots, in the order you would see them")
lib = portraits.Library(os.path.join(tmp, "portraits"))
w = watcher.Watcher(lib=lib, shot_dir=os.path.join(tmp, "captures"), stable_polls=2)
for name in ["challenge", "challenge", "prebattle", "prebattle", "prebattle", "victory", "victory",
             "victory", "stats", "stats", "stats", "challenge", "challenge"]:
    w.step(shot(name))
for t, e in reversed(w.status()["events"]):
    print("     >", e)
check("battles saved", w.saved, 1)
b = conn.execute("SELECT * FROM battles ORDER BY id DESC LIMIT 1").fetchone()
check("battle", (b["result"], b["source"], b["needs_review"], b["rank_before"], b["rank_after"],
                 b["stars_delta"], b["opp_stars_delta"], b["my_power"], b["opp_power"]),
      ("win", "auto", 0, 304, 215, 16, -8, 1984386, 1495460))
check("opponent", "Vinh Quang" in b["opp_name"], True)
check("screenshot kept", os.path.isfile(b["shot"]), True)
rows = conn.execute("SELECT team, primary_cmd, lane, col, row, troops, remaining, kills, healed FROM marches "
                    "WHERE battle_id=? ORDER BY team, primary_cmd", (b["id"],)).fetchall()
check("marches", [tuple(r) for r in rows], [
    ("enemy", "Cao Cao", "front", 0, 0, 76000, 0, 34708, 1397),
    ("enemy", "Lohar", "front", 0, 3, 70000, 0, 34923, 2197),
    ("enemy", "Mulan", "front", 0, 2, 72720, 0, 39269, 0),
    ("enemy", "Pelagius", "back", 1, 2, 72000, 0, 51052, 3816),
    ("enemy", "Sun Tzu", "front", 0, 1, 95000, 0, 83707, 0),
    ("mine", "Bjorn Ironside", "front", 0, 1, 100000, 47873, 93142, 0),
    ("mine", "Boudica", "back", 1, 0, 92000, 68533, 39166, 7031),
    ("mine", "Cao Cao", "front", 0, 3, 90000, 0, 89881, 175),
    ("mine", "Lohar", "front", 0, 0, 97500, 65201, 44403, 9281),
    ("mine", "Sun Tzu", "back", 1, 1, 100000, 70721, 126538, 0),
])
check("enemy recognised on the challenge list afterwards", w.live_enemy["names"],
      ["Cao Cao", "Sun Tzu", "Mulan", "Lohar", "Pelagius"])
check("levels read", [m["level"] for m in w.live_enemy["marches"]], [38, 50, 34, 32, 34])
print("     unknown portraits waiting on the Teach page:", len(lib.unknown_files()))

print("same screens again do not create a duplicate")
for name in ["victory", "victory", "stats", "stats"]:
    w.step(shot(name))
check("still one auto battle", conn.execute("SELECT COUNT(*) FROM battles WHERE source='auto'").fetchone()[0], 1)
check("non-stats screen never fills stats", w._on_stats(shot("victory")), None)

print("second fight: night map, then a defeat; overlay hints along the way")
w.step(shot("prebattle_night"))
check("hint while reading", (w.hint[0].startswith("Reading line-ups, wait..."), w.hint[1]), (True, "orange"))
for _ in range(3):
    w.step(shot("prebattle_night"))
# the sample has a march caught mid-drag, so one read is rightly marked unsure
check("hint once read", (w.hint[0].startswith("Line-ups read (1 unsure). OK to start  |  win ~"), w.hint[1]), (True, "green"))
check("no filler line when there is nothing to change", "\n" in w.hint[0], False)
print("     overlay says:", w.hint[0])
w.step(shot("defeat")); w.step(shot("defeat")); w.step(shot("defeat"))
check("hint after saving", w.hint[0].startswith("LOSS saved. Continue"), True)
w.step(Image.new("RGB", (1920, 1080), (120, 140, 90))); w.step(Image.new("RGB", (1920, 1080), (120, 140, 90)))
check("idle state", w.hint[0], "Watching  |  session 1W 1L")
check("roster filled by itself", conn.execute("SELECT COUNT(*) FROM roster").fetchone()[0] >= 5, True)
b2 = conn.execute("SELECT * FROM battles ORDER BY id DESC LIMIT 1").fetchone()
check("defeat saved", (b2["result"], b2["rank_before"], b2["rank_after"], b2["stars_delta"]), ("loss", 162, 227, -14))
check("enemy troops", [r[0] for r in conn.execute("SELECT troops FROM marches WHERE battle_id=? AND team='enemy' ORDER BY slot", (b2["id"],))],
      [100000, 85800, 95500, 84000, 79000])
w.step(shot("challenge")); w.step(shot("challenge"))
check("challenge hint: scanned count and win chance only", bool(re.match(r"Scanned \d/5  \|  win ~\d+%$", w.hint[0].splitlines()[0])), True)
check("bar shows the scanned line-up strip and counts the scan", ((w.bar_strip or b"")[1:4], w.scan_seq >= 1), (b"PNG", True))
print("     overlay says:", w.hint[0])

print("Lost Canyon challenge list")
for _ in range(4):      # the list is re-read every third poll
    w.step(shot("challenge_lost"))
check("Lost Canyon recognised", (w.screen, w.live_enemy["mode"]), ("challenge", "lost"))
check("no 'best of scouted' while the win chance cannot tell opponents apart", "Best of" in w.hint[0], False)
check("Lost Canyon levels", [m["level"] for m in w.live_enemy["marches"]], [42, 45, 52, 50, 60])
print("     overlay says:", w.hint[0])

print("commander screen fills the roster")
w.step(shot("commander")); w.step(shot("commander"))
check("commander hint", w.hint[0], "Sun Tzu saved: level 60, 6 stars. Next: SKILLS, then the gear '?' popup")
w.step(shot("skills")); w.step(shot("skills"))
check("skills hint", w.hint[0], "Sun Tzu skills saved: 5 5 5 5, expertised")
w.skills_seen = None; w._cmd_name = "Aethelflaed"
w.step(shot("skills_aethel")); w.step(shot("skills_aethel"))
check("non-maxed skills go to skills, not the talent tree", (w.hint[0], w.talents_saved), ("Aethelflaed skills saved: 5 3 5 1", None))
w._cmd_name = "Sun Tzu"
w.step(shot("gearstats")); w.step(shot("gearstats"))
check("gear hint", w.hint[0], "Sun Tzu gear saved: 12 stat bonuses")
check("roster row", tuple(conn.execute("SELECT level, skills, stars, power, updated<>'' FROM roster WHERE name='Sun Tzu'").fetchone()), (60, "5555E", 6, 86400, 1))
import numpy as np  # noqa: E402
before = len(w.events)
flicker = np.asarray(shot("commander")).astype(int); mm = flicker.max(2) >= 70; flicker[mm] = np.clip(flicker[mm] * 1.2 + 10, 71, 255)
w.step(Image.fromarray(flicker.astype(np.uint8)))
check("animated background does not trigger a re-read", len(w.events), before)
check("unread commanders are marked unknown, not level 60", conn.execute("SELECT level FROM roster WHERE name='Boudica'").fetchone()[0], 0)
check("report uses the gear that was read", [d["gear_txt"] for d in engine.investment_report(conn)["mine"] if d["name"] == "Sun Tzu"], ["infantry +48.5%"])

w.step(shot("talents")); w.step(shot("talents"))
check("talent screen filed under the commander", (w.hint[0], os.path.isfile(os.path.join(tmp, "captures", "talents_Sun Tzu.jpg"))),
      ("Talent screen saved for Sun Tzu", True))

print("scouting log, expertise, troop edit")
check("scouted line-ups stored once each", conn.execute("SELECT COUNT(*) FROM scouted").fetchone()[0], 2)
check("expertised frames on the Lost Canyon list", [m["expert"] for m in w.live_enemy["marches"]], [True, True, False, False, False])
meta = engine.investment_report(conn)["meta"]
check("meta counts fought and scouted line-ups", (meta["lineups"] >= 3, meta["commanders"][0][0] in ("Sun Tzu", "Cao Cao")), (True, True))

conn.close()

print("leaderboard: an opened row is scouted like the challenge list")
seq = w.scan_seq
for name in ["leaderboard_1", "leaderboard_1"]:
    w.step(shot(name))
check("leaderboard scan on the bar", (bool(re.match(r"Scanned \d/5  \|  win ~\d+%", w.hint[0])), w.scan_seq > seq, (w.bar_strip or b"")[1:4]),
      (True, True, b"PNG"))

print("background reads: the bar says 'captured' at once, the read finishes behind it")
import queue  # noqa: E402
import time  # noqa: E402
wb = watcher.Watcher(lib=lib, shot_dir=os.path.join(tmp, "captures"), stable_polls=2)
wb._jobs = queue.Queue()
threading.Thread(target=wb._work, daemon=True).start()


def drain(timeout=60):
    end = time.time() + timeout
    while wb._busy and time.time() < end:
        time.sleep(0.05)


got = []
for name in ["prebattle", "prebattle"]:
    wb.step(shot(name))
got.append(wb.hint[0])
drain()
wb.step(shot("prebattle"))
got.append(wb.hint[0].split(".")[0])
for name in ["victory", "victory"]:
    wb.step(shot(name))
got.append(wb.hint[0])
for name in ["stats", "stats"]:             # stats arrive while the result may still be reading: queued behind it
    wb.step(shot(name))
drain()
check("captured messages", got, ["Line-ups captured. OK to start (reading...)", "Line-ups read",
                                 "Result captured. Continue"])
check("result and stats saved in order", (wb.saved, wb.last_battle["stats_done"]), (1, True))

print("start-up code")
import symtable  # noqa: E402
_mod = symtable.symtable(open(os.path.join(HERE, "app.py"), encoding="utf-8").read(), "app.py", "exec")
_main = next(t for t in _mod.get_children() if t.get_name() == "main")
_imported = {s.get_name() for s in _mod.get_symbols() if s.is_imported()}
# a module imported again inside main() is a local name there: using it earlier in main() crashes the start
check("main() does not shadow module imports", sorted(_imported & {s.get_name() for s in _main.get_symbols() if s.is_local()}), [])

print("every page loads")
import app  # noqa: E402
app.WATCHER = w
app.PORT = 8799
srv = app.ThreadingHTTPServer(("127.0.0.1", app.PORT), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
for p in ["/", "/auto", "/data", "/data.json", "/history", "/history?review=1", "/teach", "/report", "/roster", "/shared", "/talents?name=Sun+Tzu",
          "/commanders", f"/battle?id={b['id']}", "/auto/status.json", "/capture.jpg", f"/shot?id={b['id']}"]:
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{app.PORT}{p}", timeout=20)
        body = r.read()
        check(p, (r.status, len(body) > 50, b"Traceback" in body), (200, True, False))
    except Exception as e:
        check(p, repr(e), "200")
mid = conn2 = None
c2 = db.connect(); mid = c2.execute("SELECT id FROM marches WHERE battle_id=? LIMIT 1", (b["id"],)).fetchone()[0]
body = f"id={b['id']}&result=win&m_{mid}_primary=Cao+Cao&m_{mid}_secondary=&m_{mid}_lane=front&m_{mid}_troops=90000".encode()
urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{app.PORT}/battle", data=body))
check("troop count editable in History", c2.execute("SELECT troops FROM marches WHERE id=?", (mid,)).fetchone()[0], 90000)
c2.close()
srv.shutdown()

shutil.rmtree(tmp, ignore_errors=True)
print("\nALL CHECKS PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
