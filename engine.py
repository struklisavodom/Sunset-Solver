"""Analysis of the fight log: win chance, formation, positioning rules, experiments, investment report."""
import json

import numpy as np
import random
import statistics
from collections import defaultdict

from priors import BEATS, GRADE_SCORE

def win_chance(conn, enemy_names, my_power=None, opp_power=None, enemy_secs=(), my_pairs=()):
    """Chance of winning against this opponent. -> (probability, fights it rests on)
    Uses only the signal that passed the held-out test in win_model; otherwise your win rate.
    enemy_secs: their secondaries; my_pairs: [(primary, secondary)] of your marches."""
    base, model, _ = win_model(conn)
    n = conn.execute("SELECT COUNT(*) FROM battles WHERE my_side='attack' AND result IN ('win','loss')").fetchone()[0]
    if model is None:
        return base, n
    kind, a, w, keys = model
    have = fight_keys([("enemy", p, "") for p in enemy_names] + [("enemy", "", s) for s in enemy_secs]
                      + [("mine", p, s) for p, s in my_pairs])
    x = ([power_feature(my_power, opp_power)] if "power" in kind else []) + [float(k in have) for k in keys]
    return float(1 / (1 + np.exp(-(a + np.array(x) @ w)))), n


def fight_keys(marches):
    """What a fight's line-ups say, as feature names: 'e:X' enemy primary, 'es:X' enemy secondary,
    'mp:P+S' one of your pairings. marches: [(team, primary, secondary)]."""
    keys = set()
    for team, p, s in marches:
        if team == "enemy":
            keys |= {f"e:{p}"} if p else set()
            keys |= {f"es:{s}"} if s else set()
        elif p and s:
            keys.add(f"mp:{p}+{s}")
    return keys


def last_pairs(conn, primaries):
    """Your newest known secondary for each of these primaries (the pre-battle screen shows none).
    -> [(primary, secondary)], skipping primaries never seen with one."""
    out = []
    for p in primaries:
        r = conn.execute("SELECT secondary_cmd FROM marches WHERE team='mine' AND primary_cmd=? AND secondary_cmd<>'' "
                         "ORDER BY battle_id DESC LIMIT 1", (p,)).fetchone()
        if p and r:
            out.append((p, r[0]))
    return out


def scouted_secondaries(conn, enemy_names):
    """Their secondaries from the newest challenge-list read of the same five primaries, or []."""
    names = {n for n in enemy_names if n}
    for (lineup,) in conn.execute("SELECT lineup FROM scouted ORDER BY id DESC"):
        rows = json.loads(lineup)
        if names and {r[0] for r in rows if r[0]} == names:
            return [r[1] for r in rows if r[1]]
    return []




def position_advice(conn, mine, enemy=None):
    """What to move before a fight. mine / enemy: [{"name", "col", "row"}], col 0 = front column,
    rows count from the top. -> list of short sentences (empty = nothing to change).

    Rules, in order (the first three come from the Sunset Canyon guides: a march attacks the
    enemy directly facing it first, then the nearest one):
      1. roles: tanks in the front column, area damage and support behind
      2. at least two marches in front, so the back line is covered
      3. against this enemy: a single-target nuker faces their tank; nobody in the back
         column stands in a row the enemy attacks with no front march covering it
      4. your own log: a commander that has clearly done better in the other column
    shortcut: row advice uses 'same row = facing' only; ranges and skill shapes are not modelled."""
    from priors import NUKERS
    roles = {r["name"]: r["role"] for r in conn.execute("SELECT name, role FROM commanders")}
    label = ("front", "back")
    tips, done = [], set()
    front = sum(m["col"] == 0 for m in mine)
    for m in mine:
        role = roles.get(m["name"], "any")
        want = {"tank": 0, "back": 1}.get(role)
        if want is None or m["col"] == want or m["name"] in done:
            continue
        keep = "tank" if want == 0 else "back"       # do not pull out someone who belongs there
        partner = next((o["name"] for o in mine if o["col"] == want and o["name"] not in done
                        and roles.get(o["name"], "any") != keep), None)
        done.add(partner)                             # a swap is one tip, not one per commander
        if want == 1 and not partner and front <= 2:
            continue                                  # would leave fewer than two marches in front
        if not partner:
            front += 1 if want == 0 else -1
        tips.append(f"Move {m['name']} to the {label[want]} column"
                    + (f" (swap with {partner})" if partner else "")
                    + (": it is a tank" if want == 0 else ": it does its work from behind"))
        done.add(m["name"])
    if len(mine) >= 4 and sum(m["col"] == 0 for m in mine) < 2 and not tips:
        tips.append("Only one march in the front column: use two or three so the back line is covered")
    if enemy:
        # their most damaging commander, judged by what it did to you before: face it with your tank
        hits = {}
        for r in conn.execute("SELECT primary_cmd, kills * 1.0 / troops FROM marches WHERE team='enemy' AND troops > 0 AND kills IS NOT NULL"):
            hits.setdefault(r[0], []).append(r[1])
        scored = [(sorted(hits[e["name"]])[len(hits[e["name"]]) // 2], e) for e in enemy if len(hits.get(e["name"], [])) >= 3]
        if scored:
            dmg, threat = max(scored, key=lambda t: t[0])
            tank = next((m for m in mine if roles.get(m["name"]) == "tank" and m["name"] not in done), None)
            if tank and dmg >= 1.0 and tank["row"] != threat["row"]:
                other = next((o["name"] for o in mine if o["row"] == threat["row"] and o["col"] == 0), None)
                tips.append(f"Their {threat['name']} hits hardest ({dmg:.1f}x its troops against you): face it with "
                            f"{tank['name']} in front row {threat['row'] + 1}" + (f" (swap with {other})" if other else ""))
                done.add(tank["name"])
        their_tank = next((e for e in enemy if e["col"] == 0 and roles.get(e["name"], "any") == "tank"), None)
        nuker = next((m for m in mine if m["name"] in NUKERS), None)
        if their_tank and nuker and nuker["row"] != their_tank["row"] and nuker["name"] not in done:
            other = next((o["name"] for o in mine if o["row"] == their_tank["row"] and o["col"] == nuker["col"]), None)
            tips.append(f"Put {nuker['name']} in row {their_tank['row'] + 1} to face their tank {their_tank['name']}"
                        + (f" (swap with {other})" if other else ""))
            done.add(nuker["name"])
        enemy_rows = {e["row"] for e in enemy}
        for m in mine:
            covered = any(o["col"] == 0 and o["row"] == m["row"] for o in mine)
            if m["col"] == 1 and not covered and m["row"] in enemy_rows and m["name"] not in done:
                tips.append(f"{m['name']} (back, row {m['row'] + 1}) has no front march covering it and an enemy "
                            f"faces that row: put a front march there or move it behind one")
                done.add(m["name"])
    for m in mine:
        if m["name"] in done:
            continue
        seen = {0: [], 1: []}
        for r in conn.execute(
                "SELECT m.col, b.result, m.troops, m.remaining FROM marches m JOIN battles b ON b.id = m.battle_id "
                "WHERE m.team='mine' AND m.primary_cmd=? AND m.col IN (0, 1)", (m["name"],)):
            win = {"win": 1.0, "draw": 0.5, "loss": 0.0}[r["result"]]
            alive = r["remaining"] / r["troops"] if r["troops"] and r["remaining"] is not None else win
            seen[r["col"]].append(0.5 * win + 0.5 * alive)
        cur, other = seen[m["col"]], seen[1 - m["col"]]
        if len(cur) >= 2 and len(other) >= 2 and sum(other) / len(other) - sum(cur) / len(cur) >= 0.15:
            tips.append(f"Try {m['name']} in the {label[1 - m['col']]} column: did better there in your log "
                        f"({len(other)} fights vs {len(cur)} here)")
    return tips[:3]


def experiment(conn, mine, enemy_names):
    """After losses, propose one change that has not been tried yet against line-ups like this.
    mine: [{"name", "col", "row"}]. -> one sentence, or None when the formation is not losing.

    It flips one march to the other column (swapping with whoever shares its row there),
    starting with the march that did least damage in those losses, and skips formations
    you already tried against similar enemies.
    shortcut: position changes only; swapping commanders in and out needs My roster filled in."""
    enemy = {n for n in enemy_names if n}
    cur = frozenset((m["name"], m["col"]) for m in mine)
    tried, wins, losses, dmg = set(), 0, 0, {}
    for b in conn.execute("SELECT id, result FROM battles WHERE my_side='attack'").fetchall():
        rows = conn.execute("SELECT team, primary_cmd, col, troops, kills FROM marches WHERE battle_id=?", (b["id"],)).fetchall()
        if len(enemy & {r["primary_cmd"] for r in rows if r["team"] == "enemy"}) < 2:
            continue
        sig = frozenset((r["primary_cmd"], r["col"]) for r in rows if r["team"] == "mine")
        tried.add(sig)
        if sig == cur:
            wins += b["result"] == "win"
            losses += b["result"] == "loss"
            if b["result"] == "loss":
                for r in rows:
                    if r["team"] == "mine" and r["troops"] and r["kills"] is not None:
                        dmg.setdefault(r["primary_cmd"], []).append(r["kills"] / r["troops"])
    if losses == 0 or losses <= wins:
        return None
    label = ("front", "back")
    weakest_first = sorted(mine, key=lambda m: sum(dmg.get(m["name"], [9])) / len(dmg.get(m["name"], [9])))
    roles = {r["name"]: r["role"] for r in conn.execute("SELECT name, role FROM commanders")}
    wrong = lambda name, col: {"tank": 0, "back": 1}.get(roles.get(name, "any"), col) != col
    for m in weakest_first:
        partner = next((o for o in mine if o["row"] == m["row"] and o["col"] != m["col"]), None)
        if wrong(m["name"], 1 - m["col"]) or (partner and wrong(partner["name"], m["col"])):
            continue                                  # never experiment against a commander's role
        new = {(x["name"], x["col"]) for x in mine} - {(m["name"], m["col"])} | {(m["name"], 1 - m["col"])}
        if partner:
            new = new - {(partner["name"], partner["col"])} | {(partner["name"], m["col"])}
        if frozenset(new) not in tried:
            return (f"Experiment: {wins}-{losses} with this formation vs similar line-ups. Try {m['name']} in the "
                    f"{label[1 - m['col']]} column" + (f" (swap with {partner['name']})" if partner else "") + ", not tried yet")
    return None


GEAR_POINTS = {"normal": 1, "advanced": 2, "elite": 3, "epic": 4, "legendary": 5}


def load_gear(path="gear.json"):
    """{commander: {slot: rarity or None}} from gear.json, or {} when the file is missing or broken."""
    try:
        with open(path, encoding="utf-8") as fh:
            return {k: v for k, v in json.load(fh).items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def gear_strength(g, troop=""):
    """-> (0..1 strength, text) for one commander's gear, or (None, "-").
    g is either stat bonuses read from the game ({"Infantry Attack": 8.0, ...}) or rarities per
    slot from gear.json. For stats, what counts is attack + defense + health of the commander's
    own troop type (the best-covered type when the troop type is not known).
    shortcut: 100% combined bonus is treated as fully geared; revisit once real ranges are known."""
    if not g:
        return None, "-"
    if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in g.values()):
        # bonuses for one troop type, plus the ones that apply to every troop ("Troop Attack", "All Troop ...")
        total = lambda t: sum(v for k, v in g.items() if k.split()[-1] in ("Attack", "Defense", "Health") and "Base" not in k
                              and (k.startswith(t) or "Troop" in k))
        t = troop if troop in ("Infantry", "Cavalry", "Archer") else max(("Infantry", "Cavalry", "Archer"), key=total)
        return min(total(t) / 100.0, 1.0), f"{t.lower()} +{total(t):g}%"
    pts = sum(GEAR_POINTS.get(r, 0) for r in g.values())
    return pts / 40.0, f"{pts}/40"


def investment_report(conn, gear=None):
    """Where to invest, from the fight log. -> {"mine": rows, "enemy": rows, "tips": [sentences]}

    Per commander: fights, how many of them you won, damage (kills / own troops) and the
    share of its troops left at the end. Sunset and Lost Canyon fights are pooled.
    shortcut: judges commanders by battle results only; actual gear and skill levels are
    not read from the game yet, so 'gear' tips say who to equip first, not which piece."""
    def side(team):
        out = {}
        for r in conn.execute(
                "SELECT m.primary_cmd n, b.result, m.troops, m.kills, m.remaining FROM marches m "
                "JOIN battles b ON b.id = m.battle_id WHERE m.team=? AND b.my_side='attack'", (team,)):
            d = out.setdefault(r["n"], {"name": r["n"], "fights": 0, "won": 0, "dmg": [], "alive": []})
            d["fights"] += 1
            d["won"] += r["result"] == "win"
            if r["troops"] and r["kills"] is not None:
                d["dmg"].append(r["kills"] / r["troops"])
            if r["troops"] and r["remaining"] is not None:
                d["alive"].append(r["remaining"] / r["troops"])
        for d in out.values():       # median: one misread troop count must not skew a commander
            d["dmg"] = statistics.median(d["dmg"]) if d["dmg"] else None
            d["alive"] = statistics.median(d["alive"]) if d["alive"] else None
        return sorted(out.values(), key=lambda d: -(d["dmg"] or 0))

    mine, enemy = side("mine"), side("enemy")
    tips = []
    if gear is None:        # stat bonuses read from the game win over the hand-written gear.json
        gear = load_gear()
        for r in conn.execute("SELECT name, gear FROM roster WHERE gear LIKE '{%'"):
            try:
                gear[r["name"]] = json.loads(r["gear"])
            except ValueError:
                pass
    troop = {r["name"]: (r["troop"] or "").capitalize() for r in conn.execute("SELECT name, troop FROM commanders")}
    for d in mine:
        d["gear"], d["gear_txt"] = gear_strength(gear.get(d["name"]), troop.get(d["name"], ""))
    rated = [d for d in mine if d["fights"] >= 3 and d["dmg"] is not None]
    if len(rated) >= 2:
        avg = sum(d["dmg"] for d in rated) / len(rated)
        top, low = rated[0], rated[-1]
        tips.append(f"{top['name']} is your main damage dealer (kills {top['dmg']:.1f}x its own troops, your average is "
                    f"{avg:.1f}x). Skill levels pay off most here.")
        role = {r["name"]: r["role"] for r in conn.execute("SELECT name, role FROM commanders")}
        dealers = [d for d in rated if role.get(d["name"]) != "tank"]          # a tank's job is to soak, not to kill
        low = dealers[-1] if dealers else None
        if low and low["dmg"] < 0.7 * avg:
            tips.append(f"{low['name']} contributes least ({low['dmg']:.1f}x). Replace it, or make it your next upgrade if it stays.")
        frail = min((d for d in rated if d["alive"] is not None), key=lambda d: d["alive"], default=None)
        if frail and frail["alive"] < 0.15:
            in_back = conn.execute("SELECT AVG(col) FROM marches WHERE team='mine' AND primary_cmd=?", (frail["name"],)).fetchone()[0] or 0
            tips.append(f"{frail['name']} is usually wiped out (keeps {frail['alive']:.0%} of its troops). Defensive gear first"
                        + ("." if in_back > 0.5 else ", or try it in the back column."))
    else:
        tips.append("Not enough fights with stats yet: tap STATS after each fight so damage per commander is recorded.")
    geared = [d for d in mine if d["gear"] is not None and d["dmg"] is not None and d["fights"] >= 3]
    if geared:
        # the next piece does most where a commander already deals damage and still has weak gear
        nxt = max(geared, key=lambda d: d["dmg"] * (1 - d["gear"]))
        tips.append(f"Next gear upgrade: {nxt['name']} (damage {nxt['dmg']:.1f}x with gear {nxt['gear_txt']}).")
    for name, g in gear.items():
        empty = [s for s in ("weapon", "helmet", "chest", "gloves", "legs", "boots") if s in g and not g[s]]
        if empty:
            tips.append(f"{name} has no {' or '.join(empty)} equipped: any piece there is a free gain.")
    owned = {r["name"] for r in conn.execute("SELECT name FROM roster")}
    fielded = {(r["primary_cmd"], r["secondary_cmd"]) for r in conn.execute(
        "SELECT DISTINCT primary_cmd, secondary_cmd FROM marches WHERE team='mine'")}
    # commanders that lead a march in most of your fights: a pairing that pulls one of them under someone else breaks a march
    nfights = conn.execute("SELECT COUNT(*) FROM battles").fetchone()[0] or 1
    leaders = {r[0] for r in conn.execute("SELECT primary_cmd FROM marches WHERE team='mine' GROUP BY primary_cmd HAVING COUNT(*) >= ?", (nfights / 2,))}
    for p in conn.execute("SELECT * FROM pairings"):
        if p["secondary_cmd"] in leaders:
            continue
        if p["primary_cmd"] in owned and p["secondary_cmd"] in owned and (p["primary_cmd"], p["secondary_cmd"]) not in fielded:
            tips.append(f"Pairing to try: {p['primary_cmd']} + {p['secondary_cmd']} ({p['note']}). Guides recommend it and you field both.")
    used = {d["name"] for d in mine}
    as_secondary = {r[0] for r in conn.execute("SELECT DISTINCT secondary_cmd FROM marches WHERE team='mine' AND secondary_cmd<>''")}
    threats = [d for d in enemy if d["fights"] >= 2 and d["dmg"] is not None][:3]
    for k, d in enumerate(threats):
        lost = d["fights"] - d["won"]
        tips.append(f"Enemy {d['name']} {'hits you hardest' if k == 0 else 'also hits hard'} ({d['dmg']:.1f}x its troops over {d['fights']} fights, you lost {lost})."
                    + ("" if d["name"] in used else
                       " You field it as a secondary; opponents get this from it as a primary." if d["name"] in as_secondary else
                       " You do not field it: worth building if you own it."))
    # what opponents field: every line-up fought plus every line-up scouted on the challenge list
    lineups = [[(r["primary_cmd"], r["secondary_cmd"]) for r in conn.execute(
        "SELECT primary_cmd, secondary_cmd FROM marches WHERE battle_id=? AND team='enemy'", (b["id"],))]
        for b in conn.execute("SELECT id FROM battles WHERE my_side='attack'").fetchall()]
    lineups += [[(m[0], m[1]) for m in json.loads(r["lineup"])] for r in conn.execute("SELECT lineup FROM scouted")]
    seen, pairs = {}, {}
    for lu in {tuple(sorted((p or "", s or "") for p, s in lu)) for lu in lineups}:     # each distinct line-up once
        for p, s in lu:
            if p:
                seen[p] = seen.get(p, 0) + 1
                if s:
                    pairs[(p, s)] = pairs.get((p, s), 0) + 1
    n = len({tuple(sorted((p or "", s or "") for p, s in lu)) for lu in lineups}) or 1
    meta = {"lineups": n,
            "commanders": sorted(((c, k, k / n) for c, k in seen.items()), key=lambda t: -t[1])[:10],
            "pairs": sorted(((f"{p} + {s}", k) for (p, s), k in pairs.items() if k >= 2), key=lambda t: -t[1])[:8]}
    return {"mine": mine, "enemy": enemy, "tips": tips, "meta": meta}


# --------------------------------------------------------------------- learned from your fights
CELLS = [(c, r) for c in (0, 1) for r in range(4)]


def battle_scores(conn):
    """{battle_id: 0..1}. A win is 0.5 plus half the share of your troops still standing; a loss is
    0.5 minus half the share of the enemy's. More informative than win/loss alone."""
    out = {}
    for b in conn.execute("SELECT id, result FROM battles WHERE my_side='attack'").fetchall():
        rows = conn.execute("SELECT team, troops, remaining FROM marches WHERE battle_id=?", (b["id"],)).fetchall()

        def left(team):
            r = [x for x in rows if x["team"] == team and x["troops"] and x["remaining"] is not None]
            return sum(x["remaining"] for x in r) / sum(x["troops"] for x in r) if r else 0.4
        out[b["id"]] = {"win": 0.5 + 0.5 * left("mine"), "loss": 0.5 - 0.5 * left("enemy"), "draw": 0.5}[b["result"]]
    return out


def power_feature(my_power, opp_power):
    """Opponent's power relative to yours, in units of 2%. 0 when unknown or implausible
    (a misread header can drop a digit; real opponents are within 1.5x of you)."""
    if my_power and opp_power and 0.67 < opp_power / my_power < 1.5:
        return float(np.log(opp_power / my_power) / 0.02)
    return 0.0


_FM = {}


def formation_model(conn):
    """How much each commander gains or loses in each grid cell, from your fights, after allowing
    for the opponent's power. Ridge regression; how far the effects may move from 0 (tau) is
    chosen by leave-one-out on your own fights, and tau = 0 ("positions do not matter") is one of
    the options. -> {(name, col, row): (effect, fights)}, empty when positions show no effect.
    Details of the last fit are in FORMATION_INFO."""
    scores = battle_scores(conn)
    obs = [(r["battle_id"], r["primary_cmd"], r["col"], r["row"]) for r in conn.execute(
        "SELECT battle_id, primary_cmd, col, row FROM marches WHERE team='mine' AND col IS NOT NULL AND row IS NOT NULL")
        if r["battle_id"] in scores]
    pairs = defaultdict(set)                       # your known pairings per fight
    for r in conn.execute("SELECT battle_id, primary_cmd, secondary_cmd FROM marches WHERE team='mine' AND secondary_cmd<>''"):
        pairs[r[0]].add((r[1], r[2]))
    key = (len(scores), max(scores) if scores else 0, len(obs), sum(map(len, pairs.values())))
    FORMATION_INFO.clear()
    if _FM.get("key") == key:
        FORMATION_INFO.update(_FM["info"])
        return _FM["val"]
    if len({o[0] for o in obs}) < 10:              # too few fights to tell anything apart
        _FM.update(key=key, val={}, info={})
        return {}
    pw = {b["id"]: power_feature(b["my_power"], b["opp_power"]) for b in conn.execute("SELECT id, my_power, opp_power FROM battles")}
    keys = sorted({(n, c, r) for _, n, c, r in obs})
    bids = sorted({o[0] for o in obs})
    bi, ki = {b: i for i, b in enumerate(bids)}, {k: i for i, k in enumerate(keys)}
    Xc = np.zeros((len(bids), len(keys)))
    for b, n, c, r in obs:
        Xc[bi[b], ki[(n, c, r)]] = 1
    pkeys = sorted({p for b in bids for p in pairs[b] if sum(p in pairs[o] for o in bids) >= 3})
    Xp = np.array([[p in pairs[b] for p in pkeys] for b in bids], float).reshape(len(bids), len(pkeys))
    Pw = np.array([[pw.get(b, 0.0)] for b in bids])
    y = np.array([scores[b] for b in bids])
    y = y - y.mean()
    # positions, pairings or both: each is one more candidate the held-out test has to pick
    variants = {"positions": np.hstack([Xc, Pw])}
    if pkeys:
        variants.update({"secondaries": np.hstack([Xp, Pw]), "positions and secondaries": np.hstack([Xc, Xp, Pw])})

    def fit(X, tau):
        lam = np.full(X.shape[1], 0.12 ** 2 / tau ** 2)
        lam[-1] = 0.12 ** 2 / 0.05 ** 2            # opponent power: its own, looser prior
        A = X.T @ X + np.diag(lam)
        H = X @ np.linalg.solve(A, X.T)
        loo = (y - H @ y) / (1 - np.diag(H))       # exact leave-one-out residuals for ridge
        return float(np.sqrt(np.mean(loo ** 2))), np.linalg.solve(A, X.T @ y)
    results = {(v, tau): fit(X, tau) for v, X in variants.items() for tau in (0.001, 0.01, 0.02, 0.03, 0.04)}
    uses, tau = min(results, key=lambda k: results[k][0])
    err0, err = results[("positions", 0.001)][0], results[(uses, tau)][0]     # tau 0.001: "nothing but power matters"
    gain = (err0 - err) / err0 if err0 > 0 else 0.0
    FORMATION_INFO.update(fights=len(bids), tau=tau, error=err, error_without=err0, gain=gain, uses=uses, pairs={},
                          pairs_tested=len(pkeys))
    val = {}
    if tau > 0.001 and gain >= 0.005:              # otherwise neither improves predictions (yet)
        eff = results[(uses, tau)][1]
        if uses.startswith("positions"):
            val = {k: (float(eff[i]), int(Xc[:, i].sum())) for k, i in ki.items()}
        if "secondaries" in uses:
            off = len(keys) if uses.startswith("positions") else 0
            FORMATION_INFO["pairs"] = {p: (float(eff[off + j]), int(Xp[:, j].sum())) for j, p in enumerate(pkeys)}
    _FM.update(key=key, val=val, info=dict(FORMATION_INFO))
    return val


FORMATION_INFO = {}


def best_formation(conn, mine, model=None):
    """Best placement of these marches by the formation model, within the rules
    (tanks in front, back-line commanders behind, at least two marches in front).
    -> (moves: [(name, (col, row) from, (col, row) to)], expected gain on the 0..1 battle score)"""
    from itertools import permutations
    model = formation_model(conn) if model is None else model
    roles = {r["name"]: r["role"] for r in conn.execute("SELECT name, role FROM commanders")}
    mine = [m for m in mine if m.get("name")]
    eff = lambda n, cell: model.get((n, cell[0], cell[1]), (0.0, 0))[0]
    allowed = lambda n, cell: {"tank": cell[0] == 0, "back": cell[0] == 1}.get(roles.get(n, "any"), True)
    cur = {m["name"]: (m["col"], m["row"]) for m in mine}
    cur_val = sum(eff(n, c) for n, c in cur.items())
    ok_now = sum(c[0] == 0 for c in cur.values()) >= min(2, len(mine)) and all(allowed(n, c) for n, c in cur.items())
    best, best_val = (tuple(cur[m["name"]] for m in mine), cur_val) if ok_now else (None, None)   # ties keep what you have
    for perm in permutations(CELLS, len(mine)):
        if sum(c[0] == 0 for c in perm) < min(2, len(mine)):
            continue
        if not all(allowed(m["name"], c) for m, c in zip(mine, perm)):
            continue
        v = sum(eff(m["name"], c) for m, c in zip(mine, perm))
        if best_val is None or v > best_val + 1e-9:
            best, best_val = perm, v
    if best is None:
        return [], 0.0
    moves = [(m["name"], cur[m["name"]], c) for m, c in zip(mine, best) if c != cur[m["name"]]]
    return moves, best_val - cur_val


def _cell(c):
    return ("front" if c[0] == 0 else "back") + f" {c[1] + 1}"


def formation_tip(conn, mine):
    """One line for the bar, or None when the learned formation is no better than what is on screen."""
    moves, gain = best_formation(conn, mine)
    if not moves or gain < 0.02:                  # smaller gains are within the noise of ~40 fights
        return None
    return "From your fights: " + ", ".join(f"{n} to {_cell(to)}" for n, _, to in moves[:3]) + f" (+{gain * 100:.0f} pts)"


_WC = {}
WIN_INFO = {}       # last win_model fit: {"scored": {candidate: log-likelihood gain on held-out fights}}


def _fit_logistic(X, Y, lam=0.3):
    """Logistic regression with an L2 penalty on the weights (not the intercept), by Newton's
    method: converges in a handful of steps, where plain gradient steps needed ~1500."""
    n, k = X.shape
    Z = np.hstack([np.ones((n, 1)), X])
    pen = np.full(k + 1, lam * n)
    pen[0] = 0.0
    beta = np.zeros(k + 1)
    beta[0] = np.log(Y.mean() / (1 - Y.mean()))
    for _ in range(25):
        p = 1 / (1 + np.exp(-(Z @ beta)))
        grad = Z.T @ (Y - p) - pen * beta
        H = (Z * (p * (1 - p))[:, None]).T @ Z + np.diag(pen) + 1e-9 * np.eye(k + 1)
        step = np.linalg.solve(H, grad)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    return beta[0], beta[1:]


def win_model(conn):
    """Which signal, if any, predicts YOUR fights. Each candidate is scored on fights it had not
    seen (leave-one-out) and used only if clearly better than your plain win rate.
    -> (base rate, model or None, note); model = (kind, a, weights, enemy names)"""
    bs = conn.execute("SELECT id, result, my_power, opp_power FROM battles WHERE my_side='attack' AND result IN ('win','loss')").fetchall()
    # secondaries arrive with the stats screen, after the fight is saved: they count toward the cache key
    key = (len(bs), bs[-1]["id"] if bs else 0, conn.execute("SELECT COUNT(*) FROM marches WHERE secondary_cmd<>''").fetchone()[0])
    if _WC.get("key") == key:
        return _WC["val"]
    Y = np.array([b["result"] == "win" for b in bs], float)
    base = (Y.sum() + 1) / (len(Y) + 2)
    val = (base, None, f"your average over {len(Y)} fights; nothing predicted better yet")
    if len(Y) >= 20 and 0 < Y.mean() < 1:
        fk = [fight_keys(conn.execute("SELECT team, primary_cmd, secondary_cmd FROM marches WHERE battle_id=?",
                                      (b["id"],)).fetchall()) for b in bs]
        common = sorted({k for s in fk for k in s if sum(k in t for t in fk) >= 3})   # rarer ones cannot be learned
        group = lambda *pre: [k for k in common if k.split(":")[0] in pre]
        cols = lambda keys: np.array([[k in s for k in keys] for s in fk], float).reshape(len(Y), len(keys))
        P = np.array([[power_feature(b["my_power"], b["opp_power"])] for b in bs])
        groups = {"enemy commanders": group("e"), "secondaries": group("es", "mp"),
                  "enemy commanders and secondaries": group("e", "es", "mp")}
        cands = {"power": (P, [])}
        for label, keys in groups.items():
            cands[label] = (cols(keys), keys)
            cands["power and " + label] = (np.hstack([P, cols(keys)]), keys)
        scored = {}
        for kind, (X, _) in cands.items():
            if X.shape[1] == 0:
                continue
            ll_m = ll_c = 0.0
            for i in range(len(Y)):
                m = np.arange(len(Y)) != i
                a, w = _fit_logistic(X[m], Y[m])
                p = min(max(1 / (1 + np.exp(-(a + X[i] @ w))), 0.02), 0.98)
                q = Y[m].mean()
                ll_m += Y[i] * np.log(p) + (1 - Y[i]) * np.log(1 - p)
                ll_c += Y[i] * np.log(q) + (1 - Y[i]) * np.log(1 - q)
            scored[kind] = ll_m - ll_c
        best = max(scored, key=scored.get) if scored else None
        if best and scored[best] > 0.5:               # clearly better on fights it had not seen
            X, keys = cands[best]
            a, w = _fit_logistic(X, Y)
            val = (base, (best, a, w, keys), f"{best}, tested on {len(Y)} fights it had not seen")
        WIN_INFO.update(scored=scored)
    _WC.update(key=key, val=val)
    return val
