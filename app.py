"""Sunset Canyon helper: local web app. Run `python app.py`, open http://127.0.0.1:8765"""
import html
import json
import os
import re
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db
import engine
import priors
import sync
import updater

try:                                   # auto-logging needs pillow, numpy, scipy (see README)
    import portraits
    import vision
    import watcher as watcher_mod
    AUTO_ERR = ""
except ImportError as e:               # the rest of the app still works without them
    AUTO_ERR = str(e)

PORT = 8765
TROOPS = ["", "infantry", "cavalry", "archer"]
GRADES = ["", "S+", "S", "A+", "A", "B+", "B", "C"]
ROLES = ["any", "tank", "back"]
esc = html.escape
WATCHER = None

CSS = """
:root{--bg:#0f1216;--panel:#171b21;--panel2:#1d232b;--line:#2a313b;--text:#e8eaed;--muted:#8a94a3;
--gold:#e8a93a;--win:#5fd38d;--loss:#ff7b7b;--tip:#7cc7ff;--warn:#ffb347}
*{box-sizing:border-box}
body{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);margin:0;font-size:15px}
nav{background:var(--panel);border-bottom:2px solid var(--gold);padding:0 24px;display:flex;gap:4px;flex-wrap:wrap;
position:sticky;top:0;z-index:5}
nav b{color:var(--gold);padding:14px 16px 14px 0;letter-spacing:.5px}
nav a{color:var(--muted);text-decoration:none;font-weight:600;padding:14px 12px;border-bottom:3px solid transparent}
nav a:hover{color:var(--text)}
nav a.on{color:var(--text);border-bottom-color:var(--gold)}
.more{position:relative;display:flex}
.more .menu{display:none;position:absolute;top:100%;left:0;background:var(--panel2);border:1px solid var(--line);
border-radius:0 0 8px 8px;min-width:190px;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.more:hover .menu,.more:focus-within .menu{display:block}
.more .menu a{display:block;padding:10px 14px;border-bottom:0}
.more .menu a:hover,.more .menu a.on{background:var(--panel);color:var(--gold)}
@keyframes flash{from{background:rgba(232,169,58,.35)}to{background:transparent}}
tr.new td{animation:flash 2.5s ease-out}
.live{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--win);margin-right:6px;
box-shadow:0 0 6px var(--win)}
main{padding:24px;max-width:1150px;margin:auto}
h2{margin:6px 0 16px;font-weight:700}h3{margin:4px 0 10px;color:var(--gold);font-size:1.02em}
table{border-collapse:collapse;width:100%;margin:10px 0}
th{color:var(--muted);font-weight:600;font-size:.85em;text-transform:uppercase;letter-spacing:.4px}
td,th{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
tr:hover td{background:rgba(255,255,255,.02)}
tr.add td{opacity:.75}
input,select,textarea{background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
input:focus,select:focus{outline:none;border-color:var(--gold)}
input[type=number]{width:80px}
button{background:var(--gold);color:#1a1205;border:0;border-radius:6px;padding:8px 16px;cursor:pointer;font-weight:700}
button:hover{filter:brightness(1.1)}
button.grey{background:var(--panel2);color:var(--text);border:1px solid var(--line);font-weight:600}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:16px 0}
.win{color:var(--win)}.loss{color:var(--loss)}.draw{color:var(--warn)}.muted{color:var(--muted);font-size:.9em}
.warn{color:var(--warn)}
.tip{color:var(--tip)}
li.tip-item{margin:6px 0;color:var(--tip)}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:.8em;font-weight:700;margin-right:6px}
.badge.win{background:rgba(95,211,141,.15)}.badge.loss{background:rgba(255,123,123,.15)}.badge.draw{background:rgba(255,179,71,.15)}
.badge.mode{background:var(--panel2);color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:16px}
.stats{display:flex;gap:16px;flex-wrap:wrap}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 20px;min-width:150px}
.stat b{display:block;font-size:1.8em;color:var(--gold)}
.tiles{display:flex;flex-wrap:wrap;gap:14px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;text-align:center}
.tile img{width:110px;height:110px;display:block;margin:0 auto 8px}
img.preview{max-width:100%;border:1px solid var(--line);border-radius:8px}
.face{position:relative;display:inline-block;flex:none;width:var(--s,28px);height:var(--s,28px);vertical-align:middle;
background:var(--gold);clip-path:polygon(25% 3%,75% 3%,100% 50%,75% 97%,25% 97%,0 50%)}
.face img,.face i{position:absolute;inset:2px;width:calc(100% - 4px);height:calc(100% - 4px);object-fit:cover;
clip-path:inherit;background:var(--panel2)}
.face i{display:flex;align-items:center;justify-content:center;font-style:normal;font-weight:700;color:var(--gold);
font-size:calc(var(--s,28px) * .36);z-index:0}.face img{z-index:1;transform:scale(1.25);object-position:50% 30%}
.legend{font-size:.8em;margin-left:10px}.legend b{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px}
.cmd{display:inline-flex;align-items:center;gap:8px}
.team{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.team .head{color:var(--muted);font-size:.85em;text-transform:uppercase;letter-spacing:.6px;text-align:center}
.cell{position:relative;display:flex;align-items:center;gap:14px;background:var(--panel2);border:1px solid var(--line);
border-left:4px solid var(--role,var(--line));border-radius:10px;padding:12px 14px;min-height:96px}
.cell.tank{--role:var(--tip)}.cell.back{--role:var(--loss)}.cell.any{--role:var(--gold)}
.cell.empty{background:transparent;border:1px dashed var(--line)}
.cell:hover,.cell:focus{border-color:var(--gold);outline:none}
.cell b{display:block;font-size:1.05em}.cell .sec{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:.9em;margin-top:6px}
.cell .meta{margin-left:auto;text-align:right;color:var(--muted);font-size:.85em}
.cell .pop{display:none;position:absolute;z-index:4;left:0;top:100%;margin-top:6px;width:320px;background:var(--panel);
border:1px solid var(--gold);border-radius:8px;padding:10px 12px;box-shadow:0 8px 24px rgba(0,0,0,.5);font-size:.9em}
.cell:hover .pop,.cell:focus .pop{display:block}
.pop div{display:flex;justify-content:space-between;gap:10px;padding:2px 0}.pop div span:first-child{color:var(--muted)}
pre{white-space:pre-wrap;background:var(--bg);padding:10px;border-radius:6px;overflow:auto}
a{color:var(--tip)}
"""


NAV = [("/", "Home"), ("/report", "Report"), ("/history", "History"), ("/roster", "My commanders"), ("/shared", "Shared"), ("/data", "Data")]
MORE = [("/auto", "Auto-log"), ("/teach", "Teach portraits"), ("/commanders", "Commanders")]


def page(title, body):
    on = lambda label: label == title or (title.startswith(label) and label != "Home")
    link = lambda href, label: f'<a href="{href}"{" class=on" if on(label) else ""}>{label}</a>'
    more_on = any(on(label) for _, label in MORE)
    links = "".join(link(h, l) for h, l in NAV) + (
        f'<div class=more><a href="#" class="{"on" if more_on else ""}" onclick="return false">More &#9662;</a>'
        f'<div class=menu>{"".join(link(h, l) for h, l in MORE)}</div></div>')
    return f"""<!doctype html><html><head><meta charset=utf-8><title>{esc(title)} - Sunset helper</title>
<style>{CSS}</style></head><body><nav><b>SUNSET HELPER</b>{links}</nav><main>{body}</main></body></html>"""


def face(name, size=28):
    """A commander's learned portrait in the game's hex frame; initials when none is learned yet."""
    if not name:
        return ""
    initials = "".join(w[0] for w in name.split()[:2]).upper()
    return (f'<span class=face style="--s:{size}px"><i>{esc(initials)}</i>'
            f'<img src="/face?name={esc(name)}" alt="" loading=lazy onerror="this.remove()"></span>')


def cmd(name, size=28):
    """Portrait + name, used wherever a commander is listed."""
    return f'<span class=cmd>{face(name, size)}{esc(name or "?")}</span>'


def _face_file(name):
    if AUTO_ERR:
        return ""
    return portraits.face_file(WATCHER.lib.root if WATCHER else "portraits", name)


def options(items, selected=""):
    return "".join(
        f'<option value="{esc(i)}"{" selected" if i == selected else ""}>{esc(i) or "-"}</option>'
        for i in items
    )


def datalist(conn):
    names = [r["name"] for r in conn.execute("SELECT name FROM commanders")]
    names = sorted(set(names) | set(priors.KNOWN_NAMES) | {f"{n} Prime" for n in priors.PRIME_BASES})
    return "<datalist id=cmds>" + "".join(f'<option value="{esc(n)}">' for n in names) + "</datalist>"


def home(conn):
    q = lambda sql: conn.execute(sql).fetchone()[0]
    nb, w = q("SELECT COUNT(*) FROM battles"), q("SELECT COUNT(*) FROM battles WHERE result='win'") or 0
    rv = q("SELECT COUNT(*) FROM battles WHERE needs_review=1")
    last10 = [r[0] for r in conn.execute("SELECT result FROM battles ORDER BY id DESC LIMIT 10")]
    form = "".join(f'<span class="badge {r}">{r[0].upper()}</span>' for r in reversed(last10)) or "-"
    base, wm, wnote = engine.win_model(conn)
    engine.formation_model(conn)
    fi = engine.FORMATION_INFO
    review = f'<p><a href="/history?review=1" class=warn>{rv} fight(s) to check</a></p>' if rv else ""
    up = updater.STATUS
    update = (f"""<div class=card><h3>Update available <span class=muted>(version {up['remote']}, you have {up['local']})</span></h3>
<form method=post action=/update><button>Update now</button></form></div>""" if up["available"] else "")
    return page("Home", f"""<h2>Sunset Canyon helper</h2>{update}
<div class=stats>
<div class=stat><b>{nb}</b>fights logged</div>
<div class=stat><b>{f"{100 * w / nb:.0f}%" if nb else "-"}</b>won</div>
<div class=stat><b>{q("SELECT COUNT(*) FROM scouted")}</b>line-ups scouted</div>
<div class=stat><b>{q("SELECT COUNT(*) FROM roster WHERE updated<>''")}</b>commanders read</div>
</div>
<div class=card><h3>Last 10 fights</h3>{form}{review}</div>
<div class=card><h3>What predicts your fights <span class=muted>(re-tested after every fight)</span></h3>
<p><b>Win chance:</b> {esc(wnote)}.</p>
<p><b>Formation:</b> {(f"positions help ({fi['gain'] * 100:.1f}% better on unseen fights): the bar gives formation tips")
                      if fi.get("gain", 0) >= 0.005 and fi.get("tau", 0) > 0.001 and fi.get("uses", "positions").startswith("positions") else
                      "no measurable effect yet: the bar uses the guide rules"}.</p>
<p><b>Secondaries:</b> {esc(_secondaries_note(wm, fi))}.</p>
</div>""")


def shared_page(conn):
    st = sync.STATUS
    if not sync.load_config():
        return page("Shared", f"""<h2>Shared</h2><div class=card><h3>Not connected</h3>
{f"<p class=warn>{esc(st['error'])}</p>" if st.get("error") else ""}<ol>
<li>Create a free project at supabase.com.</li>
<li>In its SQL editor, run:<pre>{esc(sync.SCHEMA_SQL)}</pre></li>
<li>Project Settings &gt; API Keys: copy the <b>publishable</b> key (<code>sb_publishable_...</code>) into
<code>shared.json</code> next to app.py. Never the secret key: this file goes to your friends.
<pre>{{"url": "https://xxxx.supabase.co", "key": "sb_publishable_..."}}</pre></li>
<li>Restart the app. Give your friends the same <code>shared.json</code>.</li></ol></div>""")
    pool = sync.pooled(conn)
    state = {"on": f"synced {st['last']}", "error": f"<span class=warn>{esc(st['error'])}</span>",
             "off": "starting..."}[st["state"]]
    rows = "".join(f"<tr><td>{cmd(n)}</td><td>{k}</td><td>{w:.0%}</td></tr>" for n, k, w in pool["enemies"][:15])
    return page("Shared", f"""<h2>Shared <span class=muted>{state}, you are player {esc(sync.player_id(conn))}</span></h2>
<div class=stats>
<div class=stat><b>{pool['players']}</b>players</div>
<div class=stat><b>{pool['fights']}</b>fights pooled</div>
<div class=stat><b>{f"{pool['won'] / pool['fights']:.0%}" if pool['fights'] else "-"}</b>won, everyone</div>
</div>
<div class=card><h3>Hardest enemy commanders, everyone's fights <span class=muted>(5+ fights)</span></h3>
<table><tr><th>Enemy commander</th><th>Fights</th><th>Won against it</th></tr>
{rows or '<tr><td colspan=3 class=muted>not enough pooled fights yet</td></tr>'}</table></div>""")


def _secondaries_note(wm, fi):
    """One sentence on whether secondaries (yours and theirs) passed the held-out test."""
    used = [what for what, on in (("the win chance", wm and "secondaries" in wm[0]),
                                  ("the formation score", "secondaries" in fi.get("uses", "") and fi.get("pairs"))) if on]
    if used:
        return "used in " + " and ".join(used)
    return "no measurable effect yet (too few fights per pairing)"


def commanders_page(conn):
    rows = conn.execute("SELECT * FROM commanders ORDER BY name").fetchall()
    body = ""
    for r in rows:
        body += (
            f'<tr><form method=post action=/commanders><td><input type=hidden name=name value="{esc(r["name"])}">{esc(r["name"])}</td>'
            f'<td><select name=troop>{options(TROOPS, r["troop"])}</select></td>'
            f'<td><select name=role>{options(ROLES, r["role"])}</select></td>'
            f'<td><select name=grade>{options(GRADES, r["grade"])}</select></td>'
            f'<td><button>save</button></td></form></tr>'
        )
    return page("Commanders", f"""<h2>Commanders</h2>
<p class=muted>Role decides the column rules: tanks front, back-line behind.</p>
<form method=post action=/commanders class=card><input name=name placeholder="new commander" required>
<select name=troop>{options(TROOPS)}</select><select name=role>{options(ROLES)}</select>
<select name=grade>{options(GRADES)}</select><button>Add</button></form>
<table><tr><th>Name</th><th>Troop</th><th>Role</th><th>Canyon grade</th><th></th></tr>{body}</table>""")


def _talent_file(name):
    """Where the watcher keeps the talent-screen picture of a commander."""
    folder = WATCHER.shot_dir if WATCHER else "captures"
    return os.path.join(folder, f"talents_{re.sub(r'[^A-Za-z0-9 .' + chr(39) + '-]', '_', name).strip() or 'unnamed'}.jpg")


RARITY_COLOUR = {"legendary": "#e8a93a", "epic": "#b56ae0", "elite": "#4b9be0", "advanced": "#5fb85f", "normal": "#a8adb5"}


def team_grid(conn):
    """Your line-up from the newest fight as the game's 2 x 4 grid (back column left, front right,
    as on the pre-battle screen), with each march's details on hover."""
    bid = conn.execute("SELECT MAX(battle_id) FROM marches WHERE team='mine' AND col IS NOT NULL").fetchone()[0]
    if bid is None:
        return ""
    b = conn.execute("SELECT * FROM battles WHERE id=?", (bid,)).fetchone()
    marches = {(m["col"], m["row"]): m for m in conn.execute(
        "SELECT * FROM marches WHERE battle_id=? AND team='mine' AND col IS NOT NULL", (bid,))}
    roster = {r["name"]: r for r in conn.execute("SELECT * FROM roster")}
    troop = {r["name"]: (r["troop"] or "").capitalize() for r in conn.execute("SELECT name, troop FROM commanders")}
    roles = {r["name"]: r["role"] or "any" for r in conn.execute("SELECT name, role FROM commanders")}
    cells_fx = engine.formation_model(conn)
    pairs_fx = engine.FORMATION_INFO.get("pairs") or {}

    def cell(col, row):
        m = marches.get((col, row))
        if m is None:
            return "<div class='cell empty'></div>"
        name, sec = m["primary_cmd"], m["secondary_cmd"]
        guess = ""
        if not sec:                                    # not read in this fight: show the last one seen, marked
            last = engine.last_pairs(conn, [name])
            sec, guess = (last[0][1], " (last seen)") if last else ("", "")
        r = roster.get(name)
        try:
            gear = json.loads(r["gear"]) if r and (r["gear"] or "").startswith("{") else None
        except ValueError:
            gear = None
        rec = conn.execute("SELECT COUNT(*), SUM(b.result='win') FROM marches m JOIN battles b ON b.id=m.battle_id "
                           "WHERE m.team='mine' AND m.primary_cmd=? AND m.secondary_cmd=? AND ?<>''", (name, sec, sec)).fetchone()
        fx = cells_fx.get((name, col, row))
        info = [("Secondary", (sec or "not read yet") + guess),
                ("Level / stars", f"{r['level'] or '-'} / {r['stars'] or '-'}" if r and r["updated"] else "open it in the game (P)"),
                ("Skills", " ".join((r["skills"] or "").replace("E", "")) + (" expertised" if "E" in (r["skills"] or "") else "")
                 if r and r["skills"] else "-"),
                ("Power", _num(r["power"]) if r else "-"),
                ("Gear", engine.gear_strength(gear, troop.get(name, ""))[1]),
                ("Troops", _num(m["troops"])),
                ("Last fight", f"kills {_num(m['kills'])}, left {_num(m['remaining'])}"),
                ("This pairing", f"{rec[0]} fights, {rec[1] or 0} won" if sec and not guess else "-")]
        if fx:
            info.append(("This cell", f"{fx[0] * 100:+.1f} pts ({fx[1]} fights)"))
        if (name, sec) in pairs_fx:
            info.append(("Pairing effect", f"{pairs_fx[(name, sec)][0] * 100:+.1f} pts"))
        pop = "".join(f"<div><span>{esc(k)}</span><span>{esc(str(v))}</span></div>" for k, v in info)
        lvl = f"Lv {r['level']}" if r and r["updated"] and r["level"] else ""
        return (f"<div class='cell {esc(roles.get(name, 'any'))}' tabindex=0>{face(name, 64)}<div><b>{esc(name)}</b>"
                f"<span class=sec>{face(sec, 22) if sec else ''}{esc(sec or 'secondary not read')}{esc(guess)}</span></div>"
                f"<span class=meta>{lvl}<br>{_num(m['troops'])}</span><div class=pop>{pop}</div></div>")
    grid = "<div class=head>Back</div><div class=head>Front</div>" + "".join(
        cell(1, row) + cell(0, row) for row in range(4))
    return (f"<div class=card><h3>Current team <span class=muted>from fight #{bid}, {esc((b['ts'] or '')[5:16])}</span>"
            f"<span class='legend muted'><b style='background:var(--tip)'></b>tank<b style='background:var(--loss)'></b>back line"
            f"<b style='background:var(--gold)'></b>any</span></h3>"
            f"<div class=team>{grid}</div></div>")


def roster_page(conn):
    rows = conn.execute("SELECT * FROM roster ORDER BY (updated='' OR updated IS NULL), level DESC, name").fetchall()
    body = ""
    for r in rows:
        try:
            gear = json.loads(r["gear"]) if (r["gear"] or "").startswith("{") else None
        except ValueError:
            gear = None
        if not r["updated"]:
            body += f"<tr><td>{cmd(r['name'])}</td><td colspan=7 class=muted>not read yet (key P in the game)</td></tr>"
            continue
        stats = {k: v for k, v in (gear or {}).items() if isinstance(v, (int, float))}      # every bonus the popup listed
        gear_txt = ", ".join(f"{esc(k)} +{v:g}" + ("" if "Base" in k else "%") for k, v in stats.items()) or \
            '<span class=muted>open the gear view and its "?" popup</span>'
        skills = (r["skills"] or "").replace("E", "")
        tal_link = f'<a href="/talents?name={esc(r["name"])}">picture</a>' if os.path.isfile(_talent_file(r["name"])) else "-"
        body += (f"<tr><td>{cmd(r['name'])}</td><td>{r['level'] or '-'}</td><td>{r['stars'] or '-'}</td>"
                 f"<td>{' '.join(skills) or '<span class=muted>open SKILLS</span>'}{' expertised' if 'E' in (r['skills'] or '') else ''}</td>"
                 f"<td>{_num(r['power'])}</td><td>{gear_txt}</td>"
                 f"<td>{tal_link}</td><td class=muted>{esc(r['updated'])}</td></tr>")
    return page("My commanders", f"""<h2>My commanders</h2>
{team_grid(conn)}
<table><tr><th>Commander</th><th>Level</th><th>Stars</th><th>Skills</th><th>Power</th><th>Gear</th><th>Talents</th>
<th>Last read</th></tr>{body or '<tr><td colspan=8>Nobody yet.</td></tr>'}</table>""")


def data_snapshot(conn):
    """What the database holds right now: counts, plus the newest rows of each kind."""
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    fights = []
    for b in conn.execute("SELECT * FROM battles ORDER BY id DESC LIMIT 12").fetchall():
        m = conn.execute("SELECT team, COUNT(*) n, SUM(troops IS NOT NULL) t, SUM(remaining IS NOT NULL) s, "
                         "SUM(secondary_cmd<>'') sec, SUM(level IS NOT NULL) lv FROM marches WHERE battle_id=? GROUP BY team",
                         (b["id"],)).fetchall()
        by = {r["team"]: r for r in m}
        mine, en = by.get("mine"), by.get("enemy")
        fights.append({"id": b["id"], "ts": b["ts"][5:16], "result": b["result"], "mode": "Lost" if b["mode"] == "lost" else "Sunset",
                       "opp": b["opp_name"] or "", "marches": f"{mine['n'] if mine else 0}+{en['n'] if en else 0}",
                       "troops": bool(mine and en and mine["t"] == mine["n"] and en["t"] == en["n"]),
                       "stats": bool(mine and mine["s"]), "secondaries": (mine["sec"] if mine else 0) + (en["sec"] if en else 0),
                       "scouted": bool(en and en["lv"]), "power": bool(b["my_power"] and b["opp_power"]), "check": bool(b["needs_review"])})
    cmds = [{"name": r["name"], "level": r["level"], "skills": (r["skills"] or "").replace("E", "") or "-",
             "gear": "yes" if (r["gear"] or "").startswith("{") else "-", "ts": (r["updated"] or "")[5:16]}
            for r in conn.execute("SELECT * FROM roster WHERE updated<>'' ORDER BY updated DESC LIMIT 8")]
    scouts = [{"id": r["id"], "ts": r["ts"][5:16], "mode": r["mode"],
               "lineup": ", ".join(f"{x[0] or '?'}{' ' + str(x[2]) if x[2] else ''}{' (E)' if x[3] else ''}" for x in json.loads(r["lineup"]))}
              for r in conn.execute("SELECT * FROM scouted ORDER BY id DESC LIMIT 8")]
    counts = {"fights": q("SELECT COUNT(*) FROM battles"), "marches": q("SELECT COUNT(*) FROM marches"),
              "with stats": q("SELECT COUNT(DISTINCT battle_id) FROM marches WHERE remaining IS NOT NULL"),
              "scouted line-ups": q("SELECT COUNT(*) FROM scouted"), "commanders read": q("SELECT COUNT(*) FROM roster WHERE updated<>''"),
              "portraits learned": len(WATCHER.lib.names) if WATCHER else 0}
    return {"counts": counts, "fights": fights, "commanders": cmds, "scouted": scouts,
            "events": WATCHER.status()["events"][:8] if WATCHER else []}


def data_page(conn):
    return page("Data", """<h2><span class=live></span>Data, live</h2>
<div class=stats id=counts></div>
<div class=card><h3>Latest fights</h3><table id=fights></table></div>
<div class=grid><div class=card><h3>Commander reads</h3><table id=cmds></table></div>
<div class=card><h3>Scouted line-ups</h3><table id=scouts></table></div></div>
<div class=card><h3>Activity</h3><div id=events class=muted>-</div></div>
<script>
const seen = {fights: new Set(), scouts: new Set(), cmds: new Set()}; let first = true;
const tick = v => v ? '<span class=win>&#10003;</span>' : '<span class=muted>-</span>';
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function rows(kind, key, list, head, cells) {
  const out = list.map(r => { const k = key(r), isNew = !first && !seen[kind].has(k); seen[kind].add(k);
    return `<tr${isNew ? ' class=new' : ''}>${cells(r)}</tr>`; }).join('');
  return `<tr>${head.map(h => `<th>${h}</th>`).join('')}</tr>` + (out || '<tr><td class=muted>nothing yet</td></tr>');
}
async function load() {
  try {
    const d = await (await fetch('/data.json')).json();
    document.getElementById('counts').innerHTML = Object.entries(d.counts).map(([k, v]) => `<div class=stat><b>${v}</b>${k}</div>`).join('');
    document.getElementById('fights').innerHTML = rows('fights', r => r.id, d.fights,
      ['#', 'when', 'result', 'mode', 'opponent', 'marches', 'troops', 'stats', 'powers', 'scouted', 'secondaries', ''],
      r => `<td>${r.id}</td><td>${r.ts}</td><td><span class="badge ${r.result}">${r.result.toUpperCase()}</span></td><td>${r.mode}</td>
            <td>${esc(r.opp)}</td><td>${r.marches}</td><td>${tick(r.troops)}</td><td>${tick(r.stats)}</td><td>${tick(r.power)}</td>
            <td>${tick(r.scouted)}</td><td>${r.secondaries}</td><td>${r.check ? '<a class=warn href="/history?review=1">check</a>' : ''}</td>`);
    document.getElementById('cmds').innerHTML = rows('cmds', r => r.name + r.ts, d.commanders, ['commander', 'level', 'skills', 'gear', 'read'],
      r => `<td>${esc(r.name)}</td><td>${r.level || '-'}</td><td>${r.skills}</td><td>${r.gear}</td><td class=muted>${r.ts}</td>`);
    document.getElementById('scouts').innerHTML = rows('scouts', r => r.id, d.scouted, ['when', 'line-up'],
      r => `<td class=muted>${r.ts}</td><td>${esc(r.lineup)}</td>`);
    document.getElementById('events').innerHTML = d.events.map(e => esc(e[0] + '  ' + e[1])).join('<br>') || '-';
    first = false;
  } catch (e) {}
}
load(); setInterval(load, 3000);
</script>""")


def report_page(conn):
    rep = engine.investment_report(conn)
    pct = lambda v: f"{v:.0%}" if v is not None else "-"
    mult = lambda v: f"{v:.2f}x" if v is not None else "-"

    def table(rows, won_label):
        gear = lambda d: d.get("gear_txt", "-")
        body = "".join(f"<tr><td>{cmd(d['name'])}</td><td>{d['fights']}</td><td>{d['won']}</td>"
                       f"<td>{mult(d['dmg'])}</td><td>{pct(d['alive'])}</td><td>{gear(d)}</td></tr>" for d in rows)
        return (f"<table><tr><th>Commander</th><th>Fights</th><th>{won_label}</th><th title='kills / own troops'>Damage</th>"
                f"<th title='share of troops still standing'>Troops left</th><th>Gear</th></tr>{body}</table>")
    tips = "".join(f"<li class=tip-item>{esc(t)}</li>" for t in rep["tips"])
    model = engine.formation_model(conn)
    base, wm, wnote = engine.win_model(conn)
    form = ""
    for name in sorted({k[0] for k in model}, key=lambda n: -sum(v[1] for k, v in model.items() if k[0] == n)):
        cells = sorted(((engine._cell((c, r)), e, k) for (n, c, r), (e, k) in model.items() if n == name), key=lambda t: -t[1])
        if sum(k for _, _, k in cells) < 5:
            continue
        fmt = lambda t: f"{t[0]} ({t[1] * 100:+.1f}, {t[2]} fights)"
        form += f"<tr><td>{cmd(name)}</td><td>{fmt(cells[0])}</td><td>{fmt(cells[-1])}</td></tr>"
    form_card = (f"""<div class=card><h3>Formation learned from your fights</h3>
<p class=muted>Points a commander adds in a cell, on a 0 to 100 fight score.</p>
<table><tr><th>Commander</th><th>Best cell so far</th><th>Worst cell so far</th></tr>{form}</table>
</div>""" if form else "")
    pairs_card = _pairs_card(conn)
    return page("Report", f"""<h2>Where to invest</h2>
<div class=card><ul>{tips}</ul></div>
{form_card}
{pairs_card}
<div class=card><h3>What opponents field <span class=muted>({rep['meta']['lineups']} line-ups)</span></h3>
<div class=grid><table><tr><th>Commander</th><th>Line-ups</th><th>Share</th></tr>{''.join(
    f"<tr><td>{cmd(c)}</td><td>{k}</td><td>{share:.0%}</td></tr>" for c, k, share in rep['meta']['commanders'])}</table>
<table><tr><th>Common pairing</th><th>Line-ups</th></tr>{''.join(
    f"<tr><td>{esc(p)}</td><td>{k}</td></tr>" for p, k in rep['meta']['pairs']) or '<tr><td class=muted>none seen twice yet</td><td></td></tr>'}</table></div></div>
<div class=grid><div class=card><h3>Your commanders</h3>{table(rep['mine'], 'You won')}</div>
<div class=card><h3>Enemy commanders you faced</h3>{table(rep['enemy'], 'You won')}</div></div>""")


def _pairs_card(conn):
    """Your pairings: plain record per primary + secondary, plus the learned effect once it is proven."""
    eff = engine.FORMATION_INFO.get("pairs") or {}
    rows = conn.execute(
        "SELECT m.primary_cmd p, m.secondary_cmd s, COUNT(*) n, SUM(b.result='win') w, "
        "AVG(CASE WHEN m.troops > 0 THEN m.kills * 1.0 / m.troops END) dmg FROM marches m JOIN battles b ON b.id=m.battle_id "
        "WHERE m.team='mine' AND m.secondary_cmd<>'' GROUP BY 1, 2 ORDER BY 1, 3 DESC").fetchall()
    missing = conn.execute("SELECT COUNT(*) FROM marches WHERE team='mine' AND secondary_cmd=''").fetchone()[0]
    body = "".join(
        f"<tr><td>{cmd(r['p'])}</td><td>{cmd(r['s'])}</td><td>{r['n']}</td><td>{r['w']}</td>"
        f"<td>{f'{r[4]:.2f}x' if r[4] is not None else '-'}</td>"
        f"<td>{f'{eff[(r[0], r[1])][0] * 100:+.1f}' if (r[0], r[1]) in eff else '-'}</td></tr>" for r in rows)
    return f"""<div class=card><h3>Your pairings</h3>
<p class=muted>{missing} of your marches have no secondary recorded. Effect fills in once pairings are proven.</p>
<table><tr><th>Primary</th><th>Secondary</th><th>Fights</th><th>You won</th><th>Damage</th><th>Effect</th></tr>
{body or '<tr><td colspan=6 class=muted>none recorded yet</td></tr>'}</table></div>"""


def _num(v):
    return f"{v:,}" if isinstance(v, int) else "-"


def history_page(conn, query=None):
    only_review = bool(query and query.get("review"))
    where = "WHERE needs_review=1" if only_review else ""
    out = ""
    for b in conn.execute(f"SELECT * FROM battles {where} ORDER BY id DESC LIMIT 100").fetchall():
        ms = conn.execute("SELECT * FROM marches WHERE battle_id=? ORDER BY team, slot", (b["id"],)).fetchall()
        has_stats = any(m["remaining"] is not None for m in ms)

        def table(team):
            rows = ""
            for m in ms:
                if m["team"] != team:
                    continue
                pos = f"{m['lane']}" + (f", row {m['row'] + 1}" if m["row"] is not None else "")
                rows += (f"<tr><td>{cmd(m['primary_cmd'])}"
                         + (f" <span class=muted>+</span> {cmd(m['secondary_cmd'], 22)}" if m["secondary_cmd"] else "") + "</td>"
                         f"<td>{esc(pos)}</td><td>{_num(m['troops'])}</td>"
                         + (f"<td>{_num(m['remaining'])}</td><td>{_num(m['kills'])}</td>" if has_stats else "")
                         + "</tr>")
            head = "<tr><th>March</th><th>Position</th><th>Troops</th>" + \
                   ("<th>Left</th><th>Kills</th>" if has_stats else "") + "</tr>"
            return f"<table>{head}{rows}</table>"
        meta = []
        if b["opp_name"]:
            meta.append("vs " + esc(b["opp_name"]))
        if b["rank_before"]:
            meta.append(f"rank {b['rank_before']} to {b['rank_after']}")
        if b["stars_delta"] is not None:
            meta.append(f"stars {b['stars_delta']:+d}")
        meta.append(b["source"] or "manual")
        flag = f' <span class=warn>check: {esc((b["note"] or "").replace("check: ", ""))}</span>' if b["needs_review"] else \
            (f" {esc(b['note'])}" if b["note"] else "")
        out += (f"<div class=card><span class='badge {b['result']}'>{b['result'].upper()}</span>"
                f"<span class='badge mode'>{'Lost Canyon' if b['mode'] == 'lost' else 'Sunset'}</span> "
                f"<span class=muted>#{b['id']} {esc(b['ts'])}, {', '.join(meta)}</span>{flag}"
                f"<div class=grid><div><b>Mine</b>{table('mine')}</div><div><b>Enemy</b>{table('enemy')}</div></div>"
                f'<a href="/battle?id={b["id"]}"><button class=grey type=button>edit</button></a> '
                f'<form method=post action=/history/delete style="display:inline"><input type=hidden name=id value="{b["id"]}">'
                f"<button class=grey>delete</button></form></div>")
    title = "Battles to check" if only_review else "History"
    link = '<a href="/history">show all</a>' if only_review else '<a href="/history?review=1">only battles to check</a>'
    return page(title, f"<h2>{title}</h2><p>{link}</p>{out or '<p>Nothing here yet.</p>'}")


def battle_page(conn, query):
    bid = (query.get("id") or [""])[0]
    b = conn.execute("SELECT * FROM battles WHERE id=?", (bid,)).fetchone()
    if not b:
        return page("Battle", "<p>No such battle.</p>")
    rows = ""
    for m in conn.execute("SELECT * FROM marches WHERE battle_id=? ORDER BY team, slot", (bid,)):
        rows += (f"<tr><td>{m['team']}</td>"
                 f'<td><input list=cmds name="m_{m["id"]}_primary" value="{esc(m["primary_cmd"] or "")}"></td>'
                 f'<td><input list=cmds name="m_{m["id"]}_secondary" value="{esc(m["secondary_cmd"] or "")}"></td>'
                 f'<td><select name="m_{m["id"]}_lane">{options(["front", "back"], m["lane"])}</select></td>'
                 f'<td><input type=number name="m_{m["id"]}_troops" min=0 max=999999 style="width:100px" value="{m["troops"] or ""}"></td></tr>')
    for team in ("mine", "enemy"):                 # a march hidden by a game notification can be added here
        n = conn.execute("SELECT COUNT(*) FROM marches WHERE battle_id=? AND team=?", (bid, team)).fetchone()[0]
        for k in range(n, 5):
            rows += (f"<tr class=add><td>{team} <span class=muted>(add)</span></td>"
                     f'<td><input list=cmds name="new_{team}_{k}_primary" placeholder="missing march?"></td>'
                     f'<td><input list=cmds name="new_{team}_{k}_secondary"></td>'
                     f'<td><select name="new_{team}_{k}_lane">{options(["front", "back"])}</select></td>'
                     f'<td><input type=number name="new_{team}_{k}_troops" min=0 max=999999 style="width:100px"></td></tr>')
    shot = f'<p><img class=preview src="/shot?id={b["id"]}"></p>' if b["shot"] else ""
    return page("Battle", f"""<h2>Battle #{b['id']}</h2>{datalist(conn)}
<p class=muted>{esc(b['note'] or '')}</p>
<form method=post action=/battle><input type=hidden name=id value="{b['id']}">
Result <select name=result>{options(['win', 'loss', 'draw'], b['result'])}</select>
<table><tr><th>Side</th><th>Primary</th><th>Secondary</th><th>Lane</th><th>Troops</th></tr>{rows}</table>
<button>Save and mark as checked</button></form>{shot}""")


def auto_page(conn, probe=None):
    if AUTO_ERR:
        return page("Auto-log", f"""<h2>Auto-log</h2><div class=card><p class=warn>Auto-logging needs a few extra
packages ({esc(AUTO_ERR)}).</p><pre>pip install pillow numpy scipy mss pytesseract</pre>
<p>Then install the Tesseract OCR program (see README) and restart the app.</p></div>""")
    st = WATCHER.status()
    ocr = "" if st["ocr"] else ("<p class=warn>Tesseract OCR was not found, so names and numbers cannot be read. "
                                "Install it (see README) and restart the app.</p>")
    mon, region = db.get_setting(conn, "monitor", "1"), db.get_setting(conn, "region", "")
    probe_html = f"<div class=card><h3>What I read on this frame</h3><pre>{esc(probe)}</pre></div>" if probe else ""
    return page("Auto-log", f"""<h2>Auto-log</h2>{ocr}
<div class=card>
<form method=post action=/auto/toggle style="display:inline"><button id=toggle>{'Stop' if st['running'] else 'Start'}</button></form>
<span id=state style="margin-left:14px"></span>
<p id=err class=warn></p>
<p>Enemy line-up on screen: <b id=live>-</b></p>
<p>Positioning: <b id=adv>-</b></p>
</div>
<div class=grid><div class=card><h3>Activity</h3><div id=events class=muted>-</div></div>
<div class=card><h3>What I see</h3><img id=prev class=preview src="/capture.jpg">
<form method=post action=/auto/probe><button class=grey>Capture now and show what I read</button></form></div></div>
{probe_html}
<form method=post action=/auto/settings class=card><h3>Capture settings</h3>
Monitor <input type=number name=monitor min=0 max=9 value="{esc(mon)}">
Region <input name=region size=22 placeholder="left,top,width,height" value="{esc(region)}">
<p><label><input type=checkbox name=bar_in_shots value=1{" checked" if WATCHER and WATCHER.bar_in_shots else ""}>
Show the status bar in my screenshots</label> <span class=muted>(keep it in its corner: over the game it would be read too)</span></p>
<button class=grey>Save</button>
<p class=muted>Monitor 1 is the main screen. If the game runs in a window, enter the window's game area as a
region (pixels), for example 0,31,1600,900.</p></form>
<script>
async function tick(){{
  try{{
    const s = await (await fetch('/auto/status.json')).json();
    document.getElementById('state').textContent = (s.running ? 'Watching' : 'Stopped') + ' | screen: ' + s.screen
      + (s.pending ? ' | line-ups read, waiting for result' : '') + ' | saved this session: ' + s.saved
      + (s.unknown ? ' | ' + s.unknown + ' portrait(s) to name' : '');
    document.getElementById('toggle').textContent = s.running ? 'Stop' : 'Start';
    document.getElementById('err').textContent = s.error || '';
    document.getElementById('live').textContent = s.live_enemy ? s.live_enemy.map(n => n || '?').join(', ') : '-';
    document.getElementById('adv').textContent = s.advice ? (s.advice.join(' | ') || 'nothing to change') : '-';
    document.getElementById('events').innerHTML = s.events.map(e => e[0] + '  ' + e[1].replace(/</g,'&lt;')).join('<br>') || '-';
    if (s.running) document.getElementById('prev').src = '/capture.jpg?' + Date.now();
  }}catch(e){{}}
}}
tick(); setInterval(tick, 2000);
</script>""")


def teach_page(conn):
    if AUTO_ERR:
        return page("Teach", "<p>Auto-logging packages are not installed (see Auto-log).</p>")
    lib = WATCHER.lib
    tiles = ""
    for f in lib.unknown_files():
        kind = "secondary" if f.startswith("sec_") else "primary"
        tiles += (f'<div class=tile><img src="/portrait?f={esc(f)}"><form method=post action=/teach>'
                  f'<input type=hidden name=file value="{esc(f)}"><input list=cmds name=name size=14 placeholder="who is this?">'
                  f'<br><span class=muted>{kind}</span><br><button name=act value=save>Save</button> '
                  f"<button class=grey name=act value=discard>Discard</button></form></div>")
    known = ", ".join(f"{esc(n)} ({c})" for n, c in lib.counts().items()) or "none yet"
    return page("Teach portraits", f"""<h2>Teach portraits</h2>{datalist(conn)}
<p class=muted>Faces seen without a name. Name them once; discard anything that is not a commander.</p>
<div class=tiles>{tiles or '<p>Nothing to name right now.</p>'}</div>
<div class=card><b>Known so far:</b> {known}</div>""")


# ---------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, code=200, location=None, ctype="text/html; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path, ctype):
        if path and os.path.isfile(path):
            with open(path, "rb") as fh:
                return self.send(fh.read(), ctype=ctype)
        self.send(b"", 404, ctype=ctype)

    def do_GET(self):
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)
        conn = db.connect()
        try:
            if path == "/capture.jpg":
                return self.send(WATCHER.preview if WATCHER else b"", ctype="image/jpeg")
            if path == "/data.json":
                return self.send(json.dumps(data_snapshot(conn), default=str), ctype="application/json")
            if path == "/auto/status.json":
                return self.send(json.dumps(WATCHER.status() if WATCHER else {}), ctype="application/json")
            if path == "/portrait" and WATCHER:
                f = os.path.basename((query.get("f") or [""])[0])
                return self.send_file(os.path.join(WATCHER.lib.root, "_unknown", f), "image/png")
            if path == "/face":
                return self.send_file(_face_file((query.get("name") or [""])[0]), "image/png")
            if path == "/talents":
                return self.send_file(_talent_file((query.get("name") or [""])[0]), "image/jpeg")
            if path == "/shot":
                r = conn.execute("SELECT shot FROM battles WHERE id=?", ((query.get("id") or [""])[0],)).fetchone()
                return self.send_file(r["shot"] if r else "", "image/jpeg")
            simple = {"/": home, "/commanders": commanders_page, "/report": report_page, "/roster": roster_page, "/data": data_page,
                      "/auto": auto_page, "/teach": teach_page, "/shared": shared_page}
            if path in simple:
                return self.send(simple[path](conn))
            if path == "/history":
                return self.send(history_page(conn, query))
            if path == "/battle":
                return self.send(battle_page(conn, query))
            self.send(page("404", "Not found"), 404)
        finally:
            conn.close()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        g = lambda k, d="": (form.get(k, [d])[0] or d).strip()
        conn = db.connect()
        path = urlparse(self.path).path
        try:
            if path == "/commanders":
                conn.execute(
                    "INSERT INTO commanders(name, troop, role, grade) VALUES (?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET troop=excluded.troop, role=excluded.role, grade=excluded.grade",
                    (g("name"), g("troop"), g("role", "any"), g("grade")))
                conn.commit()
                return self.send("", 303, "/commanders")
            if path == "/history/delete":
                conn.execute("DELETE FROM battles WHERE id=?", (g("id"),))
                conn.commit()
                return self.send("", 303, "/history")
            if path == "/battle":
                bid = g("id")
                for m in conn.execute("SELECT id FROM marches WHERE battle_id=?", (bid,)).fetchall():
                    primary = g(f"m_{m['id']}_primary")
                    if not primary:
                        continue
                    db.ensure_commander(conn, primary)
                    db.ensure_commander(conn, g(f"m_{m['id']}_secondary"))
                    troops = g(f"m_{m['id']}_troops")
                    conn.execute("UPDATE marches SET primary_cmd=?, secondary_cmd=?, lane=?, conf=1, "
                                 "troops=CASE WHEN ?<>'' THEN ? ELSE troops END WHERE id=?",
                                 (primary, g(f"m_{m['id']}_secondary"), g(f"m_{m['id']}_lane", "front"),
                                  troops if troops.isdigit() else "", int(troops) if troops.isdigit() else None, m["id"]))
                for key in [k for k in form if k.startswith("new_") and k.endswith("_primary") and g(k)]:
                    _, team, k, _ = key.split("_")
                    p = f"new_{team}_{k}_"
                    troops = g(p + "troops")
                    db._insert_march(conn, bid, {"team": team, "slot": int(k) + 1, "lane": g(p + "lane", "front"),
                                                 "primary_cmd": g(key), "secondary_cmd": g(p + "secondary"),
                                                 "col": 0 if g(p + "lane", "front") == "front" else 1,
                                                 "troops": int(troops) if troops.isdigit() else None, "conf": 1})
                conn.execute("UPDATE battles SET result=?, needs_review=0, note='' WHERE id=?", (g("result", "win"), bid))
                conn.commit()
                return self.send("", 303, "/history")
            if path == "/quit":            # sent by a newer copy starting up
                self.send("bye")
                threading.Timer(0.3, os._exit, (0,)).start()
                return
            if path == "/update":
                try:
                    updater.update_and_restart()
                except Exception as e:
                    return self.send(page("Update", f"<h2>Update failed</h2><p class=warn>{esc(str(e))}</p><p><a href=/>back</a></p>"))
                return self.send(page("Update", "<h2>Updating...</h2><p>The new version starts in a few seconds; "
                                                "the bar shows its build when it is ready. Reload this page then.</p>"))
            if WATCHER and path == "/auto/toggle":
                WATCHER.stop() if WATCHER.running else WATCHER.start()
                return self.send("", 303, "/auto")
            if WATCHER and path == "/auto/settings":
                db.set_setting(conn, "monitor", g("monitor", "1"))
                db.set_setting(conn, "region", g("region"))
                WATCHER.bar_in_shots = g("bar_in_shots") == "1"          # applied by the bar within a second
                db.set_setting(conn, "bar_in_shots", "1" if WATCHER.bar_in_shots else "0")
                return self.send("", 303, "/auto")
            if WATCHER and path == "/auto/probe":
                try:
                    img = WATCHER.grab_once()
                    kind = vision.classify(img)
                    lib, known = WATCHER.lib, WATCHER.known_names()
                    data = {"prebattle": lambda: vision.parse_prebattle(img, lib, known),
                            "stats": lambda: vision.parse_stats(img, lib),
                            "challenge": lambda: vision.parse_challenge(img, lib),
                            "dark": lambda: vision.parse_result(img)}.get(kind, lambda: None)()
                    text = f"screen: {kind}\nOCR ready: {vision.ocr_available()}\n" + json.dumps(data, indent=1, default=str)
                except Exception as e:
                    text = f"Could not capture: {type(e).__name__}: {e}"
                return self.send(auto_page(conn, text))
            if WATCHER and path == "/teach":
                if g("act") == "discard":
                    WATCHER.lib.discard_unknown(g("file"))
                elif g("name"):
                    db.ensure_commander(conn, g("name"))
                    conn.commit()
                    WATCHER.lib.name_unknown(g("file"), g("name"))
                return self.send("", 303, "/teach")
            self.send(page("404", "Not found"), 404)
        finally:
            conn.close()


def main():
    global WATCHER
    conn = db.connect()
    priors.seed_commanders(conn)
    db.fix_names(conn, priors.KNOWN_NAMES)
    db.repair(conn)
    db.sync_roster(conn)
    conn.close()
    threading.Thread(target=sync.run_forever, daemon=True).start()     # idle without shared.json
    threading.Thread(target=updater.run_forever, daemon=True).start()  # idle without updater.REPO
    if not AUTO_ERR:
        WATCHER = watcher_mod.Watcher()
        WATCHER.start()                 # always on: no button to remember
    server = None
    for attempt in range(6):            # an older copy may still be running hidden: ask it to quit, then take over
        try:
            server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
            break
        except OSError:
            try:
                urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/quit", data=b""), timeout=2)
            except Exception:
                pass
            time.sleep(1)
    if server is None:                  # a copy too old to know /quit: show its pages; end it in Task Manager
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        return
    url = f"http://127.0.0.1:{PORT}"           # not "localhost": on Windows that can try IPv6 first and stall
    print(f"Sunset Canyon helper running at {url}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    if WATCHER and "--no-overlay" not in sys.argv:
        try:      # tkinter must own the main thread, so the web server moves to a background one
            import overlay
            threading.Thread(target=server.serve_forever, daemon=True).start()
            return overlay.run(WATCHER)
        except Exception as e:
            print(f"Overlay not available ({e}); carrying on without it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
