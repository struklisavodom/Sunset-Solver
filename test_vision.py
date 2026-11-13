"""Checks the screen reader against the four sample screenshots in testshots/.
Run:  python test_vision.py      (needs Tesseract installed, see README)"""
import os
import shutil
import sys
import tempfile

from PIL import Image

import portraits
import priors
import vision

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "testshots")
fails = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f"   expected {want!r}"))
    if not ok:
        fails.append(label)


def load(name):
    return Image.open(os.path.join(SHOTS, name + ".png")).convert("RGB")


def main():
    if not vision.ocr_available():
        print("Tesseract OCR not found; install it first (see README).")
        sys.exit(2)
    tmp = tempfile.mkdtemp()
    lib = portraits.Library(os.path.join(tmp, "portraits"))
    known = list(priors.KNOWN_NAMES)

    print("screen types")
    for n, kind in [("challenge", "challenge"), ("prebattle", "prebattle"),
                    ("victory", "dark"), ("stats", "stats")]:
        check(n, vision.classify(load(n)), kind)
    check("not a battle screen", vision.classify(Image.new("RGB", (1920, 1080), (120, 140, 90))), "other")

    print("pre-battle (empty portrait library, names read by OCR)")
    pre = vision.parse_prebattle(load("prebattle"), lib, known)
    get = lambda side: {(m["col"], m["row"]): (m["name"], m["troops"]) for m in pre[side]}
    check("my lineup", get("mine"), {(1, 0): ("Boudica", 92000), (0, 0): ("Lohar", 97500),
                                     (1, 1): ("Sun Tzu", 100000), (0, 1): ("Bjorn Ironside", 100000),
                                     (0, 3): ("Cao Cao", 90000)})
    check("enemy lineup", get("enemy"), {(0, 0): ("Cao Cao", 76000), (0, 1): ("Sun Tzu", 95000),
                                         (1, 2): ("Pelagius", 72000), (0, 2): ("Mulan", 72720),
                                         (0, 3): ("Lohar", 70000)})
    check("header power", pre["header"], {"my_power": 1984386, "opp_power": 1495460})
    check("no flags", [m["flags"] for s in ("mine", "enemy") for m in pre[s] if m["flags"]], [])

    print("learning portraits from that screen")
    for side in ("mine", "enemy"):
        for m in pre[side]:
            lib.add(m["name"], load("prebattle"), m["hex"][0], m["hex"][1], portraits.CTX_SIZE["pre"], "pre")
    check("library", sorted(lib.known_names()),
          ["Boudica", "Bjorn Ironside", "Cao Cao", "Lohar", "Mulan", "Pelagius", "Sun Tzu"][:0] or
          sorted(["Boudica", "Bjorn Ironside", "Cao Cao", "Lohar", "Mulan", "Pelagius", "Sun Tzu"]))
    lib2 = portraits.Library(os.path.join(tmp, "portraits"))      # reload from disk
    check("library survives restart", lib2.known_names(), lib.known_names())

    print("challenge list (portraits only, no names printed)")
    ch = vision.parse_challenge(load("challenge"), lib2)
    check("enemy names", [m["name"] for m in ch["marches"]], ["Cao Cao", "Sun Tzu", "Mulan", "Lohar", "Pelagius"])
    check("enemy levels", [m["level"] for m in ch["marches"]], [38, 50, 34, 32, 34])

    print("result screen")
    r = vision.parse_result(load("victory"))
    check("result", r["result"], "win")
    check("rank", (r["rank_before"], r["rank_after"]), (304, 215))
    check("stars", (r["my_stars"], r["my_delta"], r["opp_stars"], r["opp_delta"]), (1587, 16, 1563, -8))
    check("opponent name", "Vinh Quang" in r["opp_name"], True)
    check("not a result screen", vision.parse_result(load("prebattle")), None)

    print("night map and defeat")
    check("night map is a pre-battle screen", vision.classify(load("prebattle_night")), "prebattle")
    night = vision.parse_prebattle(load("prebattle_night"), None, known)
    check("night enemy", [(m["name"], m["troops"]) for m in night["enemy"]],
          [("Baibars", 100000), ("Lancelot", 85800), ("Sun Tzu", 95500), ("Cao Cao", 84000), ("Boudica", 79000)])
    check("night mine", [(m["name"], m["troops"]) for m in night["mine"]],
          [("Boudica", 92000), ("Lohar", 97500), ("Bjorn Ironside", 100000), ("Sun Tzu", 100000), ("Cao Cao", 90000)])
    d = vision.parse_result(load("defeat"))
    check("defeat", (d["result"], d["rank_before"], d["rank_after"], d["my_delta"], d["opp_delta"]),
          ("loss", 162, 227, -14, 14))

    print("Lost Canyon challenge list and Prime versions")
    check("Lost Canyon layout", vision.classify(load("challenge_lost")), "challenge")
    lc = vision.parse_challenge(load("challenge_lost"), lib2)
    check("Lost Canyon read", (lc["mode"], [m["name"] for m in lc["marches"]][1::3], [m["level"] for m in lc["marches"]]),
          ("lost", ["Sun Tzu", "Cao Cao"], [42, 45, 52, 50, 60]))
    check("Lost Canyon expertise (Lohar and Sun Tzu have silver frames)", [m["expert"] for m in lc["marches"]],
          [True, True, False, False, False])
    for shot, me, opp in (("challenge", 1982100, 1495460), ("challenge_lost", 1972590, 1924830)):
        r = vision.parse_challenge(load(shot), lib2)
        my = vision.pick_power(r["my_power_digits"], 1980000)
        check(f"{shot}: powers (stray icon digit removed)", (my, vision.pick_power(r["opp_power_digits"], my)), (me, opp))
    check("Sunset expertise (the level-50 Sun Tzu)", [m["expert"] for m in vision.parse_challenge(load("challenge"), lib2)["marches"]],
          [False, True, False, False, False])
    im = vision.normalize(load("prebattle"))
    prime = {m["name"]: vision.is_prime(im, *m["hex"]) for m in pre["enemy"]}
    check("purple (epic) portraits are not Prime", (prime["Sun Tzu"], prime["Pelagius"], prime["Lohar"]), (False, False, False))
    check("legendary frame counts as Prime for an epic's name", prime["Cao Cao"], True)

    print("commander screen")
    check("commander screen recognised", vision.classify(load("commander")), "commander")
    c = vision.parse_commander(load("commander"), known)
    check("commander read", (c["name"], c["level"], c["stars"], c["capacity"], c["power"]), ("Sun Tzu", 60, 6, 200000, 86400))
    check("skills screen", (vision.classify(load("skills")), vision.parse_skills(load("skills"))),
          ("skills", {"skills": "5555", "expert": True}))
    check("skills screen is not mistaken for anything else", vision.parse_skills(load("talents")), None)
    check("skills not maxed, one icon selected and enlarged (and a RESET button like the talent tree)",
          (vision.classify(load("skills_aethel")), vision.parse_skills(load("skills_aethel"))), ("skills", {"skills": "5351", "expert": False}))
    check("skills not maxed, another icon enlarged", (vision.classify(load("skills_lohar")), vision.parse_skills(load("skills_lohar"))),
          ("skills", {"skills": "5553", "expert": False}))
    check("talent tree still recognised", vision.classify(load("talents")), "talents")
    check("Joan: a 2 (the text reader saw a 1)", vision.parse_skills(load("skills_joan")), {"skills": "5253", "expert": False})
    check("Aethelflaed, second screenshot", vision.parse_skills(load("skills_aethel2")), {"skills": "5351", "expert": False})
    crop = load("scout_crop")
    check("expertise on a scouted line-up: only Sun Tzu's frame is silver",
          [vision.is_expert(crop, x, 172, 70) for x in (208, 358, 508, 658, 807)], [False, True, False, False, False])
    gs = vision.parse_gearstats(load("gearstats"), known)
    check("gear stats popup", (vision.classify(load("gearstats")), gs["name"], gs["stats"]),
          ("gearstats", "Sun Tzu", {"Infantry Attack": 8.0, "Infantry Defense": 24.5, "Infantry Health": 16.0,
                                    "Cavalry Defense": 7.5, "Cavalry Health": 9.5, "Archer Attack": 4.0,
                                    "Archer Defense": 3.0, "Archer Health": 4.0, "March Speed": 9.0,
                                    "Damage to Barbarians": 6.5, "Commander EXP Gain": 8.0, "Infantry Base Defense": 1.0}))

    print("leaderboard (Sunset Canyon main screen, a row opened)")
    for shot, levels, opp in (("leaderboard_1", [60, 60, 60, 60, 60], 2558450), ("leaderboard_2", [60, 56, 60, 60, 60], 2260670),
                              ("leaderboard_3", [60, 55, 50, 58, 60], 2134900)):
        img = load(shot)
        ch = vision.parse_challenge(img)
        check(f"{shot}: recognised, levels, their power",
              (vision.classify(img), vision.challenge_mode(img), [m["level"] for m in ch["marches"]] if ch else None,
               vision.pick_power(ch["opp_power_digits"], 2021535) if ch else None), ("challenge", "rank", levels, opp))
    check("stats screen is not taken for the leaderboard", vision.challenge_mode(load("stats")), None)
    print("stats screen")
    st = vision.parse_stats(load("stats"), lib2, ["Boudica", "Lohar", "Sun Tzu", "Bjorn Ironside", "Cao Cao"],
                            ["Cao Cao", "Sun Tzu", "Mulan", "Pelagius", "Lohar"])
    check("my rows", [(x["name"], x["remaining"], x["healed"], x["kills"]) for x in st["mine"]],
          [("Sun Tzu", 70721, 0, 126538), ("Bjorn Ironside", 47873, 0, 93142), ("Cao Cao", 0, 175, 89881),
           ("Boudica", 68533, 7031, 39166), ("Lohar", 65201, 9281, 44403)])
    check("enemy rows", [(x["name"], x["remaining"], x["healed"], x["kills"]) for x in st["enemy"]],
          [("Cao Cao", 0, 1397, 34708), ("Pelagius", 0, 3816, 51052), ("Sun Tzu", 0, 0, 83707),
           ("Mulan", 0, 0, 39269), ("Lohar", 0, 2197, 34923)])

    shutil.rmtree(tmp, ignore_errors=True)
    print("\nALL CHECKS PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
