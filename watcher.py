"""Background watcher: looks at the game about once a second and logs fights by itself.

    challenge list  -> remembers the enemy line-up you are looking at (for Recommend)
    pre-battle      -> reads both line-ups, positions and troop counts
    result screen   -> reads win / loss and saves the battle
    stats screen    -> adds units remaining / healed / kills and secondary commanders

Screen capture needs:  pip install mss
"""
import io
import os
import queue
import threading
import time
from collections import deque

from PIL import Image

import db
import engine
import portraits
import priors
import vision

PENDING_MAX_AGE = 30 * 60
BUILD = "14 Nov, 03:00"            # shown on the bar when idle, so you can tell a restart took effect


def screen_grabber(get_settings):
    """Returns a function that captures the configured monitor or region (call in one thread)."""
    import mss
    sct = mss.mss()

    def grab():
        s = get_settings()
        region = [int(v) for v in s.get("region", "").replace(" ", "").split(",") if v.lstrip("-").isdigit()]
        if len(region) == 4 and region[2] > 0 and region[3] > 0:
            mon = {"left": region[0], "top": region[1], "width": region[2], "height": region[3]}
        else:
            idx = int(s.get("monitor") or 1)
            mon = sct.monitors[min(max(idx, 0), len(sct.monitors) - 1)]
        shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return grab


class Watcher:
    def __init__(self, db_path=None, lib=None, shot_dir="captures", stable_polls=2, interval=0.5):
        self.db_path = db_path
        self.lib = lib or portraits.Library("portraits")
        self.shot_dir = shot_dir
        self.stable_polls = stable_polls
        self.interval = interval
        self.lock = threading.Lock()
        self.events = deque(maxlen=30)
        self.running = False
        self.screen = "-"
        self.error = ""
        self.pending = None          # parsed pre-battle waiting for its result
        self.last_battle = None      # {"id":.., "stats_done": bool, "mine": [...], "enemy": [...]}
        self.live_enemy = None       # line-up currently shown on the challenge list
        self.preview = b""           # small JPEG of the last frame
        self.saved = 0
        self.hint = ("Not watching", "grey")   # what the overlay shows: (text, colour)
        self.chance = None                    # (probability, similar fights) for the enemy on screen
        self._saved_at = 0
        self.advice = None                    # positioning tips for the line-up on screen
        self.next_time = None                 # experiment to try after a loss
        self.rotation_tip = None              # top investment tip, shown after every fifth fight
        self.wins = self.losses = 0           # this session
        self.scouted = {}                     # line-ups opened on the challenge list -> win chance
        self._strip = None                    # PNG of the scanned line-up, cut from the screen
        self.bar_strip = None                 # what the bar shows under its text: that PNG while it is current
        self.scan_seq = 0                     # +1 for every newly scanned opponent: the bar flashes
        self._cmd_key, self.cmd_seen = None, None
        self._cmd_name, self.talents_saved = None, None
        self.skills_seen, self._gear_key, self.gear_seen = None, None, None
        self._skills_fail = 0
        self._last_kind, self._same = None, 0
        self._thread = None
        # slow reads run on a worker, so the bar can say "captured, carry on" as soon as the frame is taken.
        # Without start() (tests), jobs run inline.
        self._jobs, self._busy, self._job_error = None, set(), ""

    # ------------------------------------------------------------ helpers
    def log(self, text):
        with self.lock:
            self.events.appendleft((time.strftime("%H:%M:%S"), text))

    def known_names(self):
        conn = db.connect(self.db_path)
        try:
            names = [r["name"] for r in conn.execute("SELECT name FROM commanders")]
        finally:
            conn.close()
        return list(dict.fromkeys(names + list(priors.KNOWN_NAMES) + self.lib.known_names()))

    def settings(self):
        conn = db.connect(self.db_path)
        try:
            return {"monitor": db.get_setting(conn, "monitor", "1"),
                    "region": db.get_setting(conn, "region", "")}
        finally:
            conn.close()

    # --------------------------------------------------------------- loop
    def start(self):
        if self.running:
            return
        self.running, self.error = True, ""
        self._jobs = queue.Queue()
        threading.Thread(target=self._work, daemon=True).start()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _submit(self, name, fn, img):
        """Read this frame in the background, in order; skipped while the same kind of read is queued."""
        if name in self._busy:
            return
        self._busy.add(name)
        if self._jobs is None:
            self._run(name, fn, img)
        else:
            self._jobs.put((name, fn, img))

    def _run(self, name, fn, img):
        try:
            fn(img)
            self._job_error = ""
        except Exception as e:           # keep watching whatever happens
            self._job_error = f"{type(e).__name__}: {e}"
        finally:
            self._busy.discard(name)
            self._set_hint(self.screen)

    def _work(self):
        while True:
            self._run(*self._jobs.get())

    def stop(self):
        self.running = False

    def _loop(self):
        try:
            grab = screen_grabber(self.settings)
        except Exception as e:
            self.error = f"Screen capture is not available ({e}). Run: pip install mss"
            self.running = False
            return
        self.log("Watching the screen")
        while self.running:
            t0 = time.time()
            try:
                self.step(grab())
                self.error = self._job_error
            except Exception as e:           # keep watching whatever happens
                self.error = f"{type(e).__name__}: {e}"
            time.sleep(max(0.1, self.interval - (time.time() - t0)))
        self.hint = ("Not watching", "grey")
        self.log("Stopped")

    def grab_once(self):
        """One capture for the settings page, without starting the loop."""
        img = screen_grabber(self.settings)()
        self._set_preview(img)
        return img

    def _set_preview(self, img):
        small = img.convert("RGB")
        small.thumbnail((960, 540))
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=70)
        self.preview = buf.getvalue()

    # --------------------------------------------------- one frame of work
    def step(self, img):
        img = vision.normalize(img)
        self._set_preview(img)
        kind = vision.classify(img)
        self._same = self._same + 1 if kind == self._last_kind else 1
        self._last_kind = kind
        self.screen = kind
        if self.pending and time.time() - self.pending["t"] > PENDING_MAX_AGE:
            self.pending = None
        if self._same < self.stable_polls:
            self._set_hint(kind)                     # never leave the previous screen's message up
            return kind
        # the conditions are checked again when the job runs: an earlier job may still be filling them in
        if kind == "challenge":
            self._submit("challenge", self._on_challenge, img)
        elif kind == "prebattle":
            self._submit("prebattle", self._on_prebattle, img)
        elif kind == "dark" and (self.pending or "prebattle" in self._busy):
            self._submit("result", lambda im: self.pending and self._on_result(im), img)
        elif kind == "stats" and (self._stats_wanted() or "result" in self._busy):
            self._submit("stats", lambda im: self._stats_wanted() and self._on_stats(im), img)
        elif kind == "commander":
            self._on_commander(img)
        elif kind == "talents":
            self._on_talents(img)
        elif kind == "skills":
            self._on_skills(img)
        elif kind == "gearstats":
            self._on_gearstats(img)
        self._set_hint(kind)
        return kind

    def _stats_wanted(self):
        return bool(self.last_battle and not self.last_battle["stats_done"])

    def _chance_text(self):
        return f"  |  win ~{round(self.chance[0] * 100)}%" if self.chance else ""

    def _set_hint(self, kind):
        """What the status bar shows: one short line per situation, plus at most one tip."""
        lb = self.last_battle
        fresh = kind == "challenge" and self.live_enemy and time.time() - self.live_enemy["t"] < 8
        self.bar_strip = self._strip if fresh else None
        if not vision.ocr_available():
            self.hint = ("Text reader (Tesseract) not found: nothing can be logged. See README", "red")
            return
        busy = self._busy
        if kind == "prebattle":
            if not self.pending and "prebattle" in busy:
                self.hint = ("Line-ups captured. OK to start (reading...)", "green")
            elif not self.pending:
                self.hint = ("Reading line-ups, wait...", "orange")
            else:
                unsure = sum(bool(m["flags"]) for s in ("mine", "enemy") for m in self.pending["pre"][s])
                self.hint = ("Line-ups read" + (f" ({unsure} unsure)" if unsure else "") + ". OK to start"
                             + self._chance_text() + (f"\n{self.advice[0]}" if self.advice else ""), "green")
        elif kind == "dark" and self.pending:
            self.hint = (("Result captured. Continue", "green") if "result" in busy else ("Reading result, wait...", "orange"))
        elif kind == "dark" and time.time() - self._saved_at < 60:
            self.hint = (f"{lb['res']['result'].upper()} saved. Continue (tap STATS for more data)"
                         + (f"\nNext time: {self.next_time[12:]}" if self.next_time else "")
                         + (f"\n{self.rotation_tip}" if self.rotation_tip else ""), "green")
        elif kind == "stats" and "stats" in busy:
            self.hint = ("Stats captured. Continue", "green")
        elif kind == "stats" and lb:
            self.hint = (("Stats saved. Continue", "green") if lb["stats_done"] else ("Reading stats, wait...", "orange"))
        elif kind == "stats":
            self.hint = ("This fight was not logged (line-ups were not seen)", "grey")
        elif kind == "challenge" and self.live_enemy and time.time() - self.live_enemy["t"] < 8:
            # what you need here: was it read, and the chance. Expertise and levels are stored, not shown.
            names = self.live_enemy["names"]
            text = f"Scanned {sum(bool(n) for n in names)}/{len(names)}" + (self._chance_text() or "  |  no estimate yet")
            if len(self.scouted) > 1 and max(self.scouted.values()) - min(self.scouted.values()) >= 0.05:   # only when the model tells them apart
                names, p = max(self.scouted.items(), key=lambda kv: kv[1])
                lead = ", ".join(n for n in names if n)[:40] or "unknown line-up"
                text += f"\nBest of {len(self.scouted)} scouted: ~{round(p * 100)}% ({lead})"
            p = self.chance[0] if self.chance else None
            # the line's colour is the verdict: green favourable, red unfavourable
            self.hint = (text, "white" if p is None else "green" if p >= 0.55 else "red" if p <= 0.45 else "white")
        elif kind == "challenge":
            self.hint = ("Open an opponent's arrow to scout them", "white")
        elif kind == "commander":
            self.hint = ((self.cmd_seen + ". Next: SKILLS, then the gear '?' popup", "green") if self.cmd_seen
                         else ("Reading commander, wait...", "orange"))
        elif kind == "skills":
            self.hint = ((self.skills_seen, "green") if self.skills_seen else
                         ("Cannot read these skill levels (saved as captures/fail_skills.jpg)", "red") if self._skills_fail >= 4 else
                         ("Reading skills, wait...", "orange") if self._cmd_name else
                         ("Open a commander first, then SKILLS, so I know whose skills these are", "white"))
        elif kind == "gearstats":
            self.hint = ((self.gear_seen, "green") if self.gear_seen else ("Reading gear stats, wait...", "orange"))
        elif kind == "talents":
            self.hint = ((f"Talent screen saved for {self._cmd_name}", "green") if self.talents_saved == self._cmd_name and self._cmd_name
                         else ("Open a commander first, then TALENTS, so I know whose tree this is", "white"))
        elif self.pending:
            self.hint = ("Fight under way...", "orange")
        else:
            self.hint = ("Watching" + (f"  |  session {self.wins}W {self.losses}L" if self.wins or self.losses
                                       else f"  (build {BUILD})"), "grey")
        if self.error:
            self.hint = (self.hint[0] + "\nProblem: " + self.error, self.hint[1])

    def _estimate(self, names, mine=None, theirs=None, lineup=None, enemy_lineup=None, enemy_secs=None):
        conn = db.connect(self.db_path)
        try:
            self.advice = engine.position_advice(conn, lineup, enemy_lineup) if lineup else None
            if lineup:
                tip = engine.formation_tip(conn, lineup)       # learned from your fights: goes first
                if tip:
                    # the learned formation replaces the column rules; the threat tip is about this opponent, so it stays
                    self.advice = [tip] + [a for a in self.advice if a.startswith("Their ")]
            if lineup:
                trial = engine.experiment(conn, lineup, names)
                self.advice += [trial] if trial else []
            if mine is None:      # challenge list: no troop counts, compare commander levels
                lv = sorted((r["level"] for r in conn.execute("SELECT level FROM roster")), reverse=True)[:5]
                mine = sum(lv) if len(lv) == 5 and theirs else None
            # secondaries: theirs from the challenge list, yours as last seen (neither screen before a fight shows them)
            if enemy_secs is None:
                enemy_secs = engine.scouted_secondaries(conn, names)
            prims = [m["name"] for m in lineup] if lineup else [r[0] for r in conn.execute(
                "SELECT primary_cmd FROM marches WHERE team='mine' AND battle_id=(SELECT MAX(id) FROM battles)")]
            self.chance = engine.win_chance(conn, names, mine, theirs, enemy_secs, engine.last_pairs(conn, prims))
        finally:
            conn.close()

    def _on_talents(self, img):
        """Talent tree: the point totals are too small to read reliably, so keep the picture
        (captures/talents_<commander>.jpg), filed under the commander opened just before."""
        if self.talents_saved == self._cmd_name or not self._cmd_name:
            return
        os.makedirs(self.shot_dir, exist_ok=True)
        img.save(os.path.join(self.shot_dir, f"talents_{portraits.safe_name(self._cmd_name)}.jpg"), "JPEG", quality=92)
        self.talents_saved = self._cmd_name
        self.log(f"Talent screen saved for {self._cmd_name}")

    def _save_commander(self, name, **fields):
        conn = db.connect(self.db_path)
        try:
            db.save_commander(conn, name, **fields)
        finally:
            conn.close()

    def _on_commander(self, img):
        """Main commander view: name, level, stars, power."""
        key = vision.commander_key(img)              # the printed name only: the background is animated
        if vision.same_commander(key, self._cmd_key):
            return
        c = vision.parse_commander(img, self.known_names())
        self._cmd_key, self._cmd_name, self.skills_seen = key, c["name"], None
        if not c["name"] or not c["level"]:
            self.cmd_seen = None
            return
        self._save_commander(c["name"], level=c["level"], stars=c["stars"], power=c["power"], capacity=c["capacity"])
        self.cmd_seen = f"{c['name']} saved: level {c['level']}, {c['stars']} stars"
        self.log(self.cmd_seen)

    def _on_skills(self, img):
        """SKILLS view: has no name on it, so it belongs to the commander opened just before."""
        if self.skills_seen or not self._cmd_name:
            return
        sk = vision.parse_skills(img)
        if not sk:
            self._skills_fail += 1                   # shown on the bar instead of "reading" forever
            if self._skills_fail == 4:               # keep the frame so the reader can be fixed from it
                os.makedirs(self.shot_dir, exist_ok=True)
                img.save(os.path.join(self.shot_dir, "fail_skills.jpg"), "JPEG", quality=95)
            return
        self._skills_fail = 0
        self._save_commander(self._cmd_name, skills=sk["skills"] + ("E" if sk["expert"] else ""))
        self.skills_seen = f"{self._cmd_name} skills saved: {' '.join(sk['skills'])}" + (", expertised" if sk["expert"] else "")
        self.log(self.skills_seen)

    def _on_gearstats(self, img):
        """Equipment Attributes popup: the gear's real stat bonuses."""
        key = vision.commander_key(img, "gearstats")
        if vision.same_commander(key, self._gear_key):
            return
        g = vision.parse_gearstats(img, self.known_names())
        self._gear_key = key
        if not g["name"] or not g["stats"]:
            self.gear_seen = None
            return
        self._cmd_name = g["name"]
        self._save_commander(g["name"], gear=g["stats"])
        self.gear_seen = f"{g['name']} gear saved: {len(g['stats'])} stat bonuses"
        self.log(self.gear_seen)

    def _my_power_ref(self):
        """Your usual power, from logged fights: the yardstick for reading powers on screen."""
        conn = db.connect(self.db_path)
        try:
            p = sorted(r[0] for r in conn.execute("SELECT my_power FROM battles WHERE my_power IS NOT NULL ORDER BY id DESC LIMIT 15"))
        finally:
            conn.close()
        return p[len(p) // 2] if p else None

    def _on_challenge(self, img):
        if self._same > self.stable_polls and (self._same - self.stable_polls) % 3:
            return                                   # re-read every few seconds, not every poll
        ch = vision.parse_challenge(img, self.lib, stash=True)
        if not ch:
            return
        names = [m["name"] for m in ch["marches"]]
        if self.live_enemy is None or self.live_enemy["names"] != names:
            self.scan_seq += 1
            known = [n for n in names if n]
            self.log("Enemy line-up on screen: " + (", ".join(known) if known else "portraits not learned yet")
                     + (f" (+{names.count(None)} unknown)" if known and None in names else ""))
        self.live_enemy = {"names": names, "marches": ch["marches"], "t": time.time(), "mode": ch["mode"]}
        strip = vision.normalize(img).crop(ch["strip_box"])
        strip.thumbnail((470, 100))                  # about 60% of the game's size: fits the bar
        buf = io.BytesIO()
        strip.save(buf, "PNG")
        self._strip = buf.getvalue()
        ref = self._my_power_ref()
        my = vision.pick_power(ch["my_power_digits"], ref) or ref
        opp = vision.pick_power(ch["opp_power_digits"], my)
        self._estimate(names, my, opp, enemy_secs=[m["secondary"] for m in ch["marches"] if m["secondary"]])
        if sum(bool(n) for n in names) >= 3:           # mostly recognised: worth remembering
            conn = db.connect(self.db_path)
            try:
                db.log_scout(conn, ch["mode"], ch["marches"])
            finally:
                conn.close()
        if any(names):
            self.scouted[tuple(names)] = self.chance[0]

    def _on_prebattle(self, img):
        boxes = vision.label_boxes(img)              # cheap: no OCR
        if self.pending:                             # full re-read only when a name plate moved
            old = self.pending["pre"]["boxes"]
            same = all(len(boxes[s]) == len(old[s]) and
                       all(abs(a[0] - b[0]) < 6 and abs(a[1] - b[1]) < 6 for a, b in zip(boxes[s], old[s]))
                       for s in ("mine", "enemy"))
            if same:
                return
        pre = vision.parse_prebattle(img, self.lib, self.known_names(), boxes)
        if not pre["mine"] or not pre["enemy"]:
            return
        sig = tuple(sorted((m["side"], m["name"] or "?", m["col"], m["row"])
                           for s in ("mine", "enemy") for m in pre[s]))
        if self.pending and self.pending["sig"] == sig:
            self.pending["pre"]["boxes"] = boxes     # same line-up, plates settled a few pixels away
            return
        for s in ("mine", "enemy"):
            for m in pre[s]:
                if m["name"] and m["name_src"] in ("ocr", "new"):
                    self.lib.add(m["name"], img, m["hex"][0], m["hex"][1], portraits.CTX_SIZE["pre"], "pre")
                elif not m["name"]:
                    self.lib.stash_unknown(img, m["hex"][0], m["hex"][1], portraits.CTX_SIZE["pre"], "pre")
        self.lib.prune_unknown()
        self.pending = {"pre": pre, "sig": sig, "img": img.copy(), "t": time.time()}
        self._estimate([m["name"] for m in pre["enemy"]], pre["header"].get("my_power"), pre["header"].get("opp_power"),
                       [m for m in pre["mine"] if m["name"]], [m for m in pre["enemy"] if m["name"]])
        fmt = lambda s: ", ".join(m["name"] or "?" for m in pre[s])
        self.log(f"Line-ups read. Mine: {fmt('mine')}. Enemy: {fmt('enemy')}. Waiting for the result.")

    def _on_result(self, img):
        res = vision.parse_result(img)
        if not res:
            return
        pre = self.pending["pre"]
        marches, problems = [], list(res["flags"])
        for s in ("mine", "enemy"):
            for i, m in enumerate(sorted(pre[s], key=lambda m: (m["row"], m["col"])), 1):
                name = m["name"] or f"Unknown {s} {i}"
                marches.append({"team": s, "slot": i, "lane": "front" if m["col"] == 0 else "back",
                                "primary_cmd": name, "col": m["col"], "row": m["row"],
                                "troops": m["troops"], "conf": 0.5 if m["flags"] else 1.0})
                problems += [f"{name}: {f}" for f in m["flags"]]
        note = ("check: " + "; ".join(problems)) if problems else ""
        conn = db.connect(self.db_path)
        try:
            bid = db.save_battle(
                conn, "attack", res["result"], note, marches, source="auto",
                # Lost Canyon results show no rank or star change
                mode="lost" if res["rank_before"] is None and res["my_delta"] is None else "sunset",
                needs_review=1 if problems else 0, opp_name=res["opp_name"],
                opp_power=pre["header"].get("opp_power"), my_power=pre["header"].get("my_power"),
                rank_before=res["rank_before"], rank_after=res["rank_after"],
                stars_delta=res["my_delta"], opp_stars_delta=res["opp_delta"])
            db.link_scout(conn, bid)                 # levels, expertise, secondaries from the challenge list
            problems += db.check_battle(conn, bid)
            try:
                os.makedirs(self.shot_dir, exist_ok=True)
                path = os.path.join(self.shot_dir, f"battle_{bid}.jpg")
                # full size and high quality: lets a misread be replayed later
                self.pending["img"].save(path, "JPEG", quality=95, subsampling=0)
                conn.execute("UPDATE battles SET shot=? WHERE id=?", (path, bid))
                conn.commit()
            except Exception:
                pass
        finally:
            conn.close()
        self.scouted = {}                            # the list refreshes after a fight
        self.wins += res["result"] == "win"
        self.losses += res["result"] == "loss"
        conn = db.connect(self.db_path)
        try:
            db.sync_roster(conn)
            # a rotation is five attempts: after each one, surface the top investment tip
            self.rotation_tip = ("Rotation done. " + engine.investment_report(conn)["tips"][0] + " (more on the Report tab)"
                                 if (self.saved + 1) % 5 == 0 else None)
        finally:
            conn.close()
        self.last_battle = {"id": bid, "stats_done": False, "res": res,
                            "mine": [m["primary_cmd"] for m in marches if m["team"] == "mine"],
                            "enemy": [m["primary_cmd"] for m in marches if m["team"] == "enemy"]}
        self.next_time = None
        if res["result"] == "loss":
            conn = db.connect(self.db_path)
            try:
                self.next_time = engine.experiment(conn, [m for m in pre["mine"] if m["name"]],
                                                   [m["name"] for m in pre["enemy"]])
            finally:
                conn.close()
        self.pending = None
        self.saved += 1
        self._saved_at = time.time()
        self.log(f"Saved battle #{bid}: {res['result'].upper()}"
                 + (f", rank {res['rank_before']} to {res['rank_after']}" if res["rank_before"] else "")
                 + (" (needs a quick check)" if problems else ""))

    def _on_stats(self, img):
        lb = self.last_battle
        st = vision.parse_stats(img, self.lib, lb["mine"], lb["enemy"], stash=True)
        cells = [r[k] for s in ("mine", "enemy") for r in st[s] for k in ("remaining", "kills")]
        if sum(c is not None for c in cells) < 15 or not any(cells):
            return
        rows = {s: [{"name": r["name"], "secondary": r["secondary"], "remaining": r["remaining"],
                     "healed": r["healed"], "kills": r["kills"]} for r in st[s]] for s in ("mine", "enemy")}
        conn = db.connect(self.db_path)
        try:
            n = db.update_battle_stats(conn, lb["id"], rows)
        finally:
            conn.close()
        lb["stats_done"] = True
        self.log(f"Added battle stats to #{lb['id']} ({n} of {len(lb['mine']) + len(lb['enemy'])} marches)")

    # ------------------------------------------------------------- status
    def status(self):
        with self.lock:
            events = list(self.events)
        return {"running": self.running, "screen": self.screen, "error": self.error,
                "pending": bool(self.pending), "saved": self.saved, "events": events,
                "live_enemy": self.live_enemy["names"] if self.live_enemy else None,
                "unknown": len(self.lib.unknown_files()), "ocr": vision.ocr_available(),
                "hint": self.hint[0], "advice": self.advice, "chance": self.chance[0] if self.chance else None}
