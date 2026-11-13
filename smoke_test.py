"""Self-check of the database and the analysis: run  python smoke_test.py"""
import json
import os
import tempfile

import db
import engine
import priors

path = os.path.join(tempfile.mkdtemp(), "t.db")
conn = db.connect(path)
priors.seed_commanders(conn)

for name, lvl in [("Richard I", 60), ("Yi Seong-Gye", 60), ("Sun Tzu", 55), ("Baibars", 50),
                  ("Imhotep", 60), ("Joan of Arc", 58), ("Alp Arslan", 45), ("Bjorn Ironside", 60),
                  ("Kusunoki Masashige", 52), ("Mehmed II", 40), ("Constantine I", 35)]:
    conn.execute("INSERT INTO roster(name, level) VALUES (?,?)", (name, lvl))
conn.commit()

enemy = [{"primary_cmd": "Sun Tzu", "secondary_cmd": "Baibars", "lane": "back", "troop": "archer"},
         {"primary_cmd": "Richard I", "secondary_cmd": "", "lane": "front", "troop": "infantry"}]

# Log 8 losses with Alp Arslan up front against that enemy: the learned layer should demote him there.
for _ in range(8):
    marches = [{"team": "mine", "slot": 1, "lane": "front", "primary_cmd": "Alp Arslan", "secondary_cmd": ""},
               {"team": "enemy", "slot": 1, "lane": "back", "primary_cmd": "Sun Tzu", "secondary_cmd": "Baibars"},
               {"team": "enemy", "slot": 2, "lane": "front", "primary_cmd": "Richard I", "secondary_cmd": ""}]
    db.save_battle(conn, "attack", "loss", "", marches)

# And wins should lift someone
for _ in range(8):
    marches = [{"team": "mine", "slot": 1, "lane": "front", "primary_cmd": "Bjorn Ironside", "secondary_cmd": ""},
               {"team": "enemy", "slot": 1, "lane": "back", "primary_cmd": "Sun Tzu", "secondary_cmd": "Baibars"}]
    db.save_battle(conn, "attack", "win", "", marches)

# Tiny roster must not crash
conn2 = db.connect(os.path.join(tempfile.mkdtemp(), "small.db"))
priors.seed_commanders(conn2)
conn2.execute("INSERT INTO roster(name, level) VALUES ('Richard I', 40)")
conn2.commit()
# win chance: with no model that beats it on held-out fights, it is the smoothed win rate (8 losses here)
p, n = engine.win_chance(conn, ["Sun Tzu", "Baibars", "Richard I"], 100, 100)
assert n == 16 and abs(p - (8 + 1) / (16 + 2)) < 1e-9, (p, n)
assert engine.win_chance(conn, ["Sun Tzu"], 200, 100)[0] == p          # troop ratio no longer moves it
print("Win chance OK: %.2f from %d similar fights" % (p, n))
# positioning: a tank in the back column and a back-row commander in front get swapped
tips = engine.position_advice(conn, [{"name": "Richard I", "col": 1, "row": 0}, {"name": "Yi Seong-Gye", "col": 0, "row": 0},
                                     {"name": "Imhotep", "col": 0, "row": 1}])
assert tips == ["Move Richard I to the front column (swap with Yi Seong-Gye): it is a tank"], tips   # one tip per swap
assert engine.position_advice(conn, [{"name": "Richard I", "col": 0, "row": 0}]) == []
# against an enemy: the nuker goes opposite their tank, and an uncovered back march is called out
enemy = [{"name": "Richard I", "col": 0, "row": 2}, {"name": "Sun Tzu", "col": 0, "row": 0}]
t = engine.position_advice(conn, [{"name": "Minamoto no Yoshitsune", "col": 0, "row": 0}, {"name": "Imhotep", "col": 0, "row": 2},
                                  {"name": "Mehmed II", "col": 1, "row": 0}], enemy)
assert "Put Minamoto no Yoshitsune in row 3 to face their tank Richard I (swap with Imhotep)" in t, t
t = engine.position_advice(conn, [{"name": "Imhotep", "col": 0, "row": 1}, {"name": "Mehmed II", "col": 1, "row": 0}], enemy)
assert any(x.startswith("Mehmed II (back, row 1) has no front march covering it") for x in t), t
print("Positioning OK:", tips[0])
# experiments: a formation that only loses gets one untried change; a winning one gets none
ex = os.path.join(tempfile.mkdtemp(), "ex.db"); c3 = db.connect(ex)
form = [{"name": "A", "col": 0, "row": 0}, {"name": "B", "col": 1, "row": 0}, {"name": "C", "col": 0, "row": 1}]
def fight(result, cols, kills):
    db.save_battle(c3, "attack", result, "", [{"team": "mine", "slot": i, "lane": "front", "primary_cmd": n, "col": c, "row": 0,
        "troops": 100, "kills": k} for i, (n, c, k) in enumerate(zip("ABC", cols, kills))] +
        [{"team": "enemy", "slot": i, "lane": "front", "primary_cmd": n} for i, n in enumerate(("X", "Y"))])
assert engine.experiment(c3, form, ["X", "Y"]) is None                 # no history, nothing to say
fight("loss", (0, 1, 0), (50, 10, 80))
t1 = engine.experiment(c3, form, ["X", "Y"])
assert t1.startswith("Experiment: 0-1") and "Try B in the front column (swap with A)" in t1, t1   # B did least damage
fight("loss", (1, 0, 0), (50, 10, 80))                                 # that swap was tried and lost too
t2 = engine.experiment(c3, form, ["X", "Y"])
assert "Try A" not in t2 and "Try B" not in t2 and "Try C in the back column" in t2, t2
fight("win", (0, 1, 0), (90, 90, 90))
assert engine.experiment(c3, form, ["X", "Y"]) is None                 # 1-1: not losing any more
assert engine.experiment(c3, form, ["P", "Q"]) is None                 # different enemy
print("Experiments OK:", t1)
# investment report on the experiment log above: B does least damage, enemy X/Y have no stats
rep = engine.investment_report(c3)
assert [d["name"] for d in rep["mine"]] == ["C", "A", "B"] and rep["mine"][0]["fights"] == 3
assert rep["tips"][0].startswith("C is your main damage dealer") and rep["tips"][1].startswith("B contributes least"), rep["tips"]
assert engine.investment_report(conn2)["tips"][0].startswith("Not enough fights with stats")
g = engine.investment_report(c3, {"A": {"weapon": "legendary", "helmet": "elite"}, "C": {"weapon": None, "helmet": "normal"}})
assert [d["gear_txt"] for d in g["mine"]] == ["1/40", "8/40", "-"] and g["mine"][2]["gear"] is None
assert "Next gear upgrade: C (damage 0.8x with gear 1/40)." in g["tips"] and "C has no weapon equipped: any piece there is a free gain." in g["tips"], g["tips"]
# stat bonuses read from the game: the commander's own troop type counts; unknown type -> best covered
st = {"Infantry Attack": 8.0, "Infantry Defense": 24.5, "Infantry Health": 16.0, "Cavalry Health": 9.5, "March Speed": 9.0}
assert engine.gear_strength(st, "Infantry") == (0.485, "infantry +48.5%") and engine.gear_strength(st, "Cavalry")[1] == "cavalry +9.5%"
assert engine.gear_strength(st, "")[1] == "infantry +48.5%" and engine.gear_strength(None) == (None, "-")
assert engine.gear_strength({"Troop Attack": 5.0, "Cavalry Health": 3.0, "Infantry Base Defense": 1.0}, "Cavalry")[1] == "cavalry +8%"
assert engine.load_gear("no_such_file.json") == {}
print("Report OK:", rep["tips"][1])
# formation model: a commander that only wins in one cell is moved there; nothing to say without evidence
fx = os.path.join(tempfile.mkdtemp(), "fx.db"); c4 = db.connect(fx); priors.seed_commanders(c4)
def fought(result, cells):
    db.save_battle(c4, "attack", result, "", [{"team": "mine", "slot": i, "lane": "front" if c == 0 else "back", "primary_cmd": n,
        "col": c, "row": r} for i, (n, (c, r)) in enumerate(cells.items())] + [{"team": "enemy", "slot": 0, "lane": "front", "primary_cmd": "Z"}])
form = {"P": (0, 0), "Q": (0, 1), "R": (1, 2)}
assert engine.best_formation(c4, [{"name": n, "col": c, "row": r} for n, (c, r) in form.items()])[0] == []
for _ in range(8):
    fought("win", {"P": (0, 0), "Q": (0, 1), "R": (1, 0)})
    fought("loss", {"P": (0, 0), "Q": (0, 1), "R": (1, 2)})
tip = engine.formation_tip(c4, [{"name": n, "col": c, "row": r} for n, (c, r) in form.items()])
assert tip and tip.startswith("From your fights: R to back 1"), tip
assert engine.best_formation(c4, [{"name": "Richard I", "col": 0, "row": 0}, {"name": "P", "col": 0, "row": 1}])[0] == [] or \
    all(to[0] == 0 for n, _, to in engine.best_formation(c4, [{"name": "Richard I", "col": 0, "row": 0}, {"name": "P", "col": 0, "row": 1}])[0] if n == "Richard I")
print("Formation OK:", tip)
# names: an OCR slip is merged into the real name everywhere
db.save_battle(c4, "attack", "win", "", [{"team": "mine", "slot": 0, "lane": "front", "primary_cmd": "Joan of Arc", "secondary_cmd": "Matilda Of Flander"}])
db.sync_roster(c4)
db.save_commander(c4, "Matilda Of Flander", level=40, skills="5555E")         # a roster row with data, as on the real PC
db.fix_names(c4, priors.KNOWN_NAMES)
assert c4.execute("SELECT level, skills FROM roster WHERE name='Matilda of Flanders'").fetchone()[:] == (40, "5555E")
assert not c4.execute("SELECT 1 FROM roster WHERE name='Matilda Of Flander'").fetchone()
assert c4.execute("SELECT COUNT(*) FROM marches WHERE secondary_cmd='Matilda of Flanders'").fetchone()[0] == 1
assert not c4.execute("SELECT 1 FROM commanders WHERE name='Matilda Of Flander'").fetchone()
assert c4.execute("SELECT role FROM commanders WHERE name='Joan of Arc'").fetchone()[0] == "tank"
print("Names OK")
# data checks: an impossible troop count is cleared, a missing march flagged, a misread power dropped
ck = os.path.join(tempfile.mkdtemp(), "ck.db"); c5 = db.connect(ck); priors.seed_commanders(c5)
for k in range(4):
    db.save_battle(c5, "attack", "win", "", [{"team": "mine", "slot": i, "lane": "front", "primary_cmd": n, "troops": 90000}
                   for i, n in enumerate("ABCDE")] + [{"team": "enemy", "slot": i, "lane": "front", "primary_cmd": n} for i, n in enumerate("VWXYZ")],
                   my_power=2000000, opp_power=1950000)
bid = db.save_battle(c5, "attack", "loss", "", [{"team": "mine", "slot": i, "lane": "front", "primary_cmd": n, "troops": 30000 if n == "A" else 90000}
                     for i, n in enumerate("ABCDE")] + [{"team": "enemy", "slot": i, "lane": "front", "primary_cmd": n} for i, n in enumerate("VWXY")],
                     my_power=200000, opp_power=1950000)
probs = db.check_battle(c5, bid)
assert c5.execute("SELECT troops FROM marches WHERE battle_id=? AND primary_cmd='A'", (bid,)).fetchone()[0] is None
assert c5.execute("SELECT my_power, opp_power FROM battles WHERE id=?", (bid,)).fetchone()[:] == (None, 1950000)
assert any("only 4 of their marches" in p for p in probs) and c5.execute("SELECT needs_review FROM battles WHERE id=?", (bid,)).fetchone()[0] == 1
# scouting link: levels, expertise and secondaries copied into the matching fight
c5.execute("INSERT INTO scouted(mode, key, lineup) VALUES ('sunset', 'k', ?)",
           (json.dumps([["V", "S1", 40, True], ["W", None, 50, False], ["X", "S3", 45, False], ["Y", "S4", 60, True], [None, None, None, False]]),))
assert db.link_scout(c5, bid)
assert c5.execute("SELECT level, expert, secondary_cmd FROM marches WHERE battle_id=? AND primary_cmd='V'", (bid,)).fetchone()[:] == (40, 1, "S1")
# win model: when the opponent's power really decides fights, it is found and used
wm = os.path.join(tempfile.mkdtemp(), "wm.db"); c6 = db.connect(wm)
import random
rnd = random.Random(3)
for k in range(40):
    ratio = rnd.choice((0.94, 0.97, 1.0, 1.03, 1.06))
    db.save_battle(c6, "attack", "win" if rnd.random() < (0.9 if ratio < 1 else 0.6 if ratio == 1 else 0.25) else "loss", "",
                   [{"team": "enemy", "slot": 0, "lane": "front", "primary_cmd": "E%d" % (k % 7)}], my_power=2000000, opp_power=int(2000000 * ratio))
base, model, note = engine.win_model(c6)
assert model and "power" in model[0], note
assert engine.win_chance(c6, [], 2000000, 1880000)[0] > engine.win_chance(c6, [], 2000000, 2120000)[0] + 0.3
print("Data checks, scouting link, win model OK:", note)
# impossible secondaries (a commander twice in one line-up) are cleared; a sound one stays
sb = os.path.join(tempfile.mkdtemp(), "sb.db"); c8 = db.connect(sb)
bid = db.save_battle(c8, "attack", "win", "", [{"team": "mine", "slot": i, "lane": "front", "primary_cmd": p, "secondary_cmd": s}
                     for i, (p, s) in enumerate([("A", "A"), ("B", "C"), ("C", "X"), ("D", "X"), ("E", "Y")])])
db.update_battle_stats(c8, bid, {"mine": []})
assert dict(c8.execute("SELECT primary_cmd, secondary_cmd FROM marches WHERE battle_id=?", (bid,)).fetchall()) == \
    {"A": "", "B": "", "C": "", "D": "", "E": "Y"}
# win model: when your secondary really decides fights, the pairing is found and used
sw = os.path.join(tempfile.mkdtemp(), "sw.db"); c9 = db.connect(sw)
for k in range(40):
    sec = ("S1", "S2")[k % 2]
    db.save_battle(c9, "attack", "win" if rnd.random() < (0.9 if sec == "S1" else 0.15) else "loss", "",
                   [{"team": "mine", "slot": 0, "lane": "front", "primary_cmd": "P", "secondary_cmd": sec},
                    {"team": "enemy", "slot": 0, "lane": "front", "primary_cmd": "E%d" % (k % 7)}], my_power=2000000, opp_power=2000000)
base, model, note = engine.win_model(c9)
assert model and "secondaries" in model[0], note
assert engine.win_chance(c9, [], my_pairs=[("P", "S1")])[0] > engine.win_chance(c9, [], my_pairs=[("P", "S2")])[0] + 0.15   # per-pairing weights are shrunk hard
print("Secondaries OK:", note)
# sharing: finished fights go up once, without names; other players' fights come down into shared_fights
import sync  # noqa: E402
import time  # noqa: E402
remote = []


def fake_http(method, url, key, body=None):
    if method == "POST":
        for f in body:
            if not any(r["player"] == f["player"] and r["local_id"] == f["local_id"] for r in remote):
                remote.append(dict(f, id=len(remote) + 1))
        return None
    last = int(url.split("id=gt.")[1].split("&")[0])
    return [r for r in remote if r["id"] > last]


remote.append({"id": 1, "player": "friend", "local_id": 7, "ts": "2026-11-01 10:00:00", "mode": "sunset", "my_side": "attack",
               "result": "loss", "my_power": 1, "opp_power": 1, "stars_delta": -3,
               "marches": [{"team": "enemy", "primary_cmd": "Sun Tzu"}]})
sh = os.path.join(tempfile.mkdtemp(), "sh.db"); c10 = db.connect(sh)
done = db.save_battle(c10, "attack", "win", "", [{"team": "mine", "slot": 0, "lane": "front", "primary_cmd": "A", "remaining": 5},
                                                 {"team": "enemy", "slot": 0, "lane": "front", "primary_cmd": "Sun Tzu"}],
                      opp_name="Some Player")
fresh = db.save_battle(c10, "attack", "loss", "", [{"team": "mine", "slot": 0, "lane": "front", "primary_cmd": "A"}])
cfg = {"url": "https://x.supabase.co", "key": "k"}
assert sync.sync_once(c10, cfg, fake_http) == (1, 2)          # the fight with stats goes; the fresh one waits for its stats
assert sync.sync_once(c10, cfg, fake_http) == (0, 0)          # nothing twice
assert "Some Player" not in json.dumps(remote) and [r["local_id"] for r in remote if r["player"] != "friend"] == [done]
assert sync.ready_fights(c10, now=time.time() + sync.SETTLE + 60)[0][0] == fresh   # stats never came: shared after a while
p = sync.pooled(c10)
assert (p["players"], p["fights"], p["won"]) == (2, 2, 1), p
print("Sharing OK")
# updates: program files are replaced, user data and paths outside the folder never touched
import io, zipfile, updater  # noqa: E401,E402
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    for name in ("app.py", "sub/new.py", "rok_canyon.db", "captures/battle_1.jpg", "gear.json", "shared.json",
                 "portraits/Sun Tzu/a.png", "../evil.py"):
        z.writestr("repo-main/" + name, "new")
dest = tempfile.mkdtemp()
open(os.path.join(dest, "rok_canyon.db"), "w").write("mine")
assert updater.install(buf.getvalue(), dest) == 2
assert open(os.path.join(dest, "rok_canyon.db")).read() == "mine" and os.path.isfile(os.path.join(dest, "sub", "new.py"))
assert not os.path.exists(os.path.join(dest, "captures")) and not os.path.exists(os.path.join(os.path.dirname(dest), "evil.py"))
print("Updater OK")
# threat: an enemy commander that has hit hard before gets your tank opposite it
th = os.path.join(tempfile.mkdtemp(), "th.db"); c7 = db.connect(th); priors.seed_commanders(c7)
for _ in range(3):
    db.save_battle(c7, "attack", "loss", "", [{"team": "enemy", "slot": 0, "lane": "front", "primary_cmd": "Thutmose III", "troops": 100000, "kills": 150000},
                                             {"team": "enemy", "slot": 1, "lane": "front", "primary_cmd": "Lohar", "troops": 100000, "kills": 40000}])
t = engine.position_advice(c7, [{"name": "Richard I", "col": 0, "row": 0}, {"name": "Sun Tzu", "col": 1, "row": 2}, {"name": "Imhotep", "col": 0, "row": 2}],
                           [{"name": "Thutmose III", "col": 1, "row": 2}, {"name": "Lohar", "col": 0, "row": 0}])
assert t and t[0] == "Their Thutmose III hits hardest (1.5x its troops against you): face it with Richard I in front row 3 (swap with Imhotep)", t
print("Threat OK:", t[0])
print("ALL CHECKS PASSED")
