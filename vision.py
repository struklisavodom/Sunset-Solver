"""Screen reader for the Rise of Kingdoms PC client (Sunset Canyon).

Works on a screenshot (PIL image) of the game. Everything is measured at 1920x1080 and
the input is rescaled to that first, so any 16:9 resolution works. Needs:
    pip install pillow numpy scipy pytesseract
plus the Tesseract OCR program. Without Tesseract the screens are still recognised and
portraits are still matched, but names, troop counts and numbers cannot be read.

Try it on a screenshot:   python vision.py my_screenshot.png
"""
import difflib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageOps

try:
    from scipy import ndimage as ndi
    from scipy.optimize import linear_sum_assignment
except ImportError:  # pragma: no cover
    ndi = None
    linear_sum_assignment = None
try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

import portraits
import priors
from portraits import CTX_SIZE

CANON = (1920, 1080)

# ------------------------------------------------------------------ geometry
# Hex-portrait centres of the 2 x 4 battle grid, per side (pixels at 1920x1080).
# col 0 = the column nearest the enemy ("front"), col 1 = the column behind it.
LATTICE = {
    "mine":  {"x": [[655, 631, 598, 566], [405, 361, 305, 251]], "y": [168, 301, 459, 646]},
    "enemy": {"x": [[1189, 1209, 1231, 1258], [1438, 1480, 1525, 1573]], "y": [168, 301, 459, 646]},
}
NAME_COLOUR = {"mine": (40, 255, 0), "enemy": (255, 88, 88)}

OK_BOX = (0.452, 0.925, 0.548, 0.945)          # cyan OK button (pre-battle)
REPLAY_BOX = (0.452, 0.755, 0.548, 0.775)      # cyan REPLAY button (stats)
# Challenge list: Sunset Canyon and Lost Canyon use panels of different widths. "refresh" is
# a part of the cyan REFRESH button that only that layout covers; "x" the five portrait centres.
CHALLENGE = {
    "sunset": {"refresh": (0.243, 0.238, 0.283, 0.246), "x": [680, 830, 980, 1130, 1280], "s": 66, "sec": (41, 19), "strip": (0.75, 0.8)},
    "lost":   {"refresh": (0.334, 0.2405, 0.356, 0.2455), "x": [637, 795, 953, 1111, 1269], "s": 72, "sec": (42, 13), "strip": (0.45, 1.0)},
    # Sunset Canyon main screen (leaderboard): an expanded row shows the player's defence the same way;
    # recognised by the top edge of the cyan CHALLENGE button (the stats REPLAY button there reaches ~0.7)
    "rank":   {"refresh": (0.462, 0.757, 0.538, 0.763), "min": 0.9, "x": [680, 830, 980, 1130, 1280], "s": 66,
               "sec": (41, 19), "strip": (0.75, 0.8), "my_pw": (735, 300, 845, 330), "opp_pw": (690, -118, 900, -88)},
}
STATS_ROWS = [402, 467, 532, 597, 662]
STATS_COLS = {
    "mine":  {"x": 354, "remaining": 486, "healed": 659, "kills": 832, "sec": (25, 12)},
    "enemy": {"x": 1568, "kills": 1096, "healed": 1268, "remaining": 1442, "sec": (23, 13)},
}


# ---------------------------------------------------------------------- OCR
_TESS_OK = None


OCR_PROBLEM = ""     # why OCR is off, in words the user can act on ("" when it works)


def find_tesseract():
    """tesseract.exe: TESSERACT_CMD, the folder the Windows installer records in the registry, PATH,
    then the usual folders on every drive. -> path or None"""
    import shutil
    cands = [os.environ.get("TESSERACT_CMD")]
    if os.name == "nt":
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for key in (r"SOFTWARE\Tesseract-OCR", r"SOFTWARE\WOW6432Node\Tesseract-OCR"):
                    try:
                        with winreg.OpenKey(hive, key) as k:
                            cands.append(os.path.join(winreg.QueryValueEx(k, "InstallDir")[0], "tesseract.exe"))
                    except OSError:
                        pass
        except ImportError:
            pass
    cands.append(shutil.which("tesseract"))
    if os.name == "nt":
        cands.append(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"))
        cands.append(os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"))
        for drive in "CDEFG":
            for folder in (r"Program Files\Tesseract-OCR", r"Program Files (x86)\Tesseract-OCR", "Tesseract-OCR"):
                cands.append(rf"{drive}:\{folder}\tesseract.exe")
    return next((c for c in cands if c and os.path.isfile(c)), None)


def ocr_available():
    global _TESS_OK, OCR_PROBLEM
    if _TESS_OK is None:
        _TESS_OK = False
        if pytesseract is None:
            OCR_PROBLEM = "Python package missing: run  pip install pytesseract"
            return _TESS_OK
        cmd = find_tesseract()
        if not cmd:
            OCR_PROBLEM = "Tesseract program not found: install it (README step 3) and restart"
            return _TESS_OK
        pytesseract.pytesseract.tesseract_cmd = cmd
        try:
            pytesseract.get_tesseract_version()
            _TESS_OK = True
        except Exception as e:
            OCR_PROBLEM = f"Tesseract at {cmd} does not run ({type(e).__name__}): reinstall it"
    return _TESS_OK


def _ocr(mask, psm=7, whitelist=None, scale=4):
    """OCR a boolean ink mask (True = text)."""
    if not ocr_available() or mask.size == 0:
        return ""
    arr = np.where(mask, 0, 255).astype(np.uint8)
    pil = Image.fromarray(arr).resize((arr.shape[1] * scale, arr.shape[0] * scale), Image.LANCZOS)
    pil = ImageOps.expand(pil, border=20, fill=255)
    cfg = f"--psm {psm}" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    try:
        return pytesseract.image_to_string(pil, config=cfg).strip()
    except Exception:
        return ""


def _white(img, box, thr=200, sat_max=70):
    s = np.asarray(img.crop(box)).astype(int)
    mx, mn = s.max(2), s.min(2)
    return (mn >= thr - 45) & (mx >= thr) & ((mx - mn) <= sat_max)


_NUM = re.compile(r"^\d{1,3}(,\d{3})*$")


def _best_cluster(mask, gap=14, pad=2):
    """Keep only the biggest horizontal run of ink (text), trimmed tight. Removes stray
    pixels at the edge of a crop and makes the OCR insensitive to a pixel or two of shift."""
    cols = np.where(mask.any(axis=0))[0]
    if cols.size == 0:
        return mask
    runs, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > gap:
            runs.append((start, prev))
            start = c
        prev = c
    runs.append((start, prev))
    a, b = max(runs, key=lambda r: int(mask[:, r[0]:r[1] + 1].sum()))
    sub = mask[:, a:b + 1]
    rows = np.where(sub.any(axis=1))[0]
    return sub[max(0, rows[0] - pad): rows[-1] + 1 + pad]


def _read_count(*masks):
    """Troop count under a name plate: majority vote over masks and OCR settings.
    A dropped leading digit is the usual slip, so among the top answers the longer one wins."""
    quick = [_ocr(_best_cluster(m), psm=7, whitelist="0123456789,", scale=4) for m in masks]
    if len(set(quick)) == 1 and _NUM.match(quick[0]) and 40000 <= int(quick[0].replace(",", "")) <= 999999:
        return int(quick[0].replace(",", ""))        # independent masks agree: no need for the full vote
    cands = []
    for mask in masks:
        m = _best_cluster(mask)
        for scale in (3, 4, 5):
            for psm in (7, 8):
                t = _ocr(m, psm=psm, whitelist="0123456789,", scale=scale)
                if _NUM.match(t) or re.fullmatch(r"\d{5,6}", t):
                    cands.append(int(t.replace(",", "")))
    cands = Counter(c for c in cands if 1000 <= c <= 999999)
    if not cands:
        return None
    best, n = cands.most_common(1)[0]
    for c, k in cands.items():      # e.g. 90,000 read three times beats 0,000 -> "30,000"/"5,000" style slips
        if k >= 2 and len(str(c)) > len(str(best)) and str(c).endswith(str(best)[1:]):
            best = c
    return best


def read_number(img, box):
    """Read a comma-grouped number printed in white. -> (value or None, confidence 0..1).
    Candidates that do not look like a properly comma-grouped number are rejected, which
    catches most OCR slips; a cell with ink but no readable digits is a lone zero.
    Stops as soon as two reads agree: most cells need 2 OCR calls instead of 6."""
    votes, ink, tried, digits = Counter(), 0, 0, False
    for thr in (215, 195, 235):
        m = _white(img, box, thr)
        ink = max(ink, int(m.sum()))
        for psm in (7, 8):
            c = _ocr(m, psm=psm, whitelist="0123456789,")
            tried += 1
            digits |= len(re.sub(r"\D", "", c)) >= 2
            if _NUM.match(c):
                votes[c] += 1
                if votes[c] == 2:
                    return int(c.replace(",", "")), 2 / tried
        # no digits at all: a lone zero, checked below. A misgrouped read ("89,88" for 89,881)
        # means a real number is there, so the other thresholds still get their turn.
        if tried == 2 and not votes and not digits and ink > 12:
            break
    if votes:
        v, n = votes.most_common(1)[0]
        # a single stray vote for a one-digit number is how a lone zero gets misread
        if len(v.replace(",", "")) >= 2:
            return int(v.replace(",", "")), n / tried
    if ink > 12:
        if _ocr(_white(img, box, 215), psm=10, whitelist="0123456789,", scale=6) == "0":
            return 0, 0.5
        return 0, 0.2
    return None, 0.0


def read_plain_int(img, box, mask_fn=None):
    cands = []
    for thr in (200, 175, 225):
        m = mask_fn(img, box) if mask_fn else _white(img, box, thr, sat_max=255)
        t = re.sub(r"\D", "", _ocr(m, psm=8, whitelist="0123456789"))
        if t:
            cands.append(int(t))
        if mask_fn:
            break
    if not cands:
        return None
    return Counter(cands).most_common(1)[0][0]


# ----------------------------------------------------------------- names
def _ascii(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _key(s):
    return re.sub(r"[^a-z ]", "", _ascii(s).lower()).strip()


def fix_name(raw, known):
    """Closest known commander name to OCR text. -> (name or None, score)"""
    k = _key(raw)
    if len(k) < 3:
        return None, 0.0
    best, bs = None, 0.0
    for n in known:
        sc = difflib.SequenceMatcher(None, k, _key(n)).ratio()
        if sc > bs:
            best, bs = n, sc
    return (best, bs) if bs >= 0.8 else (None, bs)


def resolve_name(raw, portrait_name, known):
    """Combine the OCR text and the portrait match. -> (name, source, flags)"""
    flags = []
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z' \-\.]", "", _ascii(raw))).strip()
    matched, _ = fix_name(cleaned, known)
    if matched:
        if portrait_name and portrait_name != matched:
            flags.append(f"portrait looks like {portrait_name}")
        return matched, "ocr", flags
    if portrait_name:
        return portrait_name, "portrait", flags
    if len(cleaned) >= 3:
        flags.append(f"new commander name '{cleaned.title()}'")
        return cleaned.title(), "new", flags
    flags.append("commander not recognised")
    return None, "none", flags


# ------------------------------------------------------------ screen type
def normalize(img):
    img = img.convert("RGB")
    if img.size != CANON:
        img = img.resize(CANON, Image.LANCZOS)
    return img


def _box(img, fb):
    W, H = img.size
    return (int(fb[0] * W), int(fb[1] * H), int(fb[2] * W), int(fb[3] * H))


def cyan_frac(img, fb):
    a = np.asarray(img.crop(_box(img, fb))).astype(int)
    if a.size == 0:
        return 0.0
    return float(((a[..., 2] > 200) & (a[..., 1] > 120) & (a[..., 0] < 90)).mean())


def level_row(img, xs, y0=460, y1=820):
    """Row of the white level digits under a line of hexes: the sharpest height cue on the leaderboard,
    where the colour-based strip finder only gives a broad plateau. -> (row, strength); strength >= 150
    when all five hexes show their level."""
    a = np.asarray(img).astype(int)
    white = []
    for r in range(y0, y1):
        seg = np.concatenate([a[r, x - 14: x + 14] for x in xs])
        white.append(int(((seg.min(1) > 215) & ((seg.max(1) - seg.min(1)) < 40)).sum()))
    sm = np.convolve(white, np.ones(9), "same")         # the digits are ~14 px tall
    i = int(sm.argmax())
    return y0 + i, int(sm[i])


def challenge_mode(img):
    """'sunset' | 'lost' when the challenge list is showing, 'rank' on the leaderboard, else None."""
    for mode, L in CHALLENGE.items():
        if cyan_frac(img, L["refresh"]) > L.get("min", 0.6):
            return mode
    return None


def is_prime(img, cx, cy, s=62):
    """Epic portraits have a purple background; the legendary Prime of the same name does not."""
    a = np.asarray(img.crop((int(cx - 0.4 * s), int(cy - 0.42 * s), int(cx + 0.4 * s), int(cy + 0.3 * s)))).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return float(((b > 120) & (r > 90) & (g < 0.6 * b) & (g < 0.75 * r) & (b > r * 0.95)).mean()) < 0.03


def is_expert(img, cx, cy, s):
    """Expertised commanders have a pale silver hex frame instead of gold. Measures the upper
    half of the frame ring (the lower right is covered by the secondary), at the best of a few
    small shifts. Main portraits only: a secondary's frame is too thin to judge reliably."""
    a = np.asarray(img).astype(int)
    r = int(0.6 * s)
    ys, xs = np.mgrid[-r:r + 1, -r:r + 1]
    d = np.maximum(np.abs(xs), np.abs(xs) / 2 + np.abs(ys) * np.sqrt(3) / 2)     # pointy-top hex distance
    band = (d >= 0.43 * s) & (d <= 0.53 * s) & (ys < 0)
    best = 0.0
    for dx in range(-8, 9, 2):          # the frame is found by looking around, not assumed
        for dy in range(-8, 9, 2):
            yy, xx = ys[band] + int(round(cy)) + dy, xs[band] + int(round(cx)) + dx
            ok = (yy >= 0) & (yy < a.shape[0]) & (xx >= 0) & (xx < a.shape[1])
            p = a[yy[ok], xx[ok]]
            if len(p):
                mx, mn = p.max(1), p.min(1)
                best = max(best, float(((mn > 150) & (mx - mn < 60)).mean()))
    # measured on 17 portraits: expertised 0.42-0.51, normal 0.00-0.17
    return best >= 0.30


def pick_power(digits, ref):
    """Power from a digit string that may carry a stray leading digit: the reading (7, 8 or 9
    digits) closest to ref. None when nothing is within 1.5x of it."""
    opts = [int(digits[-k:]) for k in (7, 8, 9) if len(digits) >= k and digits[-k] != "0"]
    opts = [o for o in opts if ref and 0.67 < o / ref < 1.5]
    return min(opts, key=lambda o: abs(np.log(o / ref))) if opts else None


def classify(img):
    """-> 'prebattle' | 'stats' | 'challenge' | 'dark' (maybe the result screen) | 'other'"""
    img = normalize(img)
    if cyan_frac(img, OK_BOX) > 0.6:
        return "prebattle"
    if cyan_frac(img, REPLAY_BOX) > 0.5:
        r, g, b = np.asarray(img.crop(_box(img, (0.625, 0.425, 0.705, 0.44)))).reshape(-1, 3).mean(0)
        if r > b + 50 and r > g + 50:
            return "stats"
    if challenge_mode(img):
        return "challenge"
    a = np.asarray(img.crop((1100, 276, 1450, 290))).astype(int)
    if float((a.min(2) > 235).mean()) > 0.6:
        return "gearstats"                           # white "Equipment Attributes" popup
    # TALENTS and SKILLS buttons side by side; a strip above and one below the label, either may match
    both = lambda x0, x1: max(cyan_frac(img, (x0, 0.716, x1, 0.730)), cyan_frac(img, (x0, 0.757, x1, 0.768)))
    if both(0.790, 0.862) > 0.5 and both(0.900, 0.972) > 0.5:
        return "commander"
    small = np.asarray(img.resize((96, 54))).astype(float)
    if small[..., 2].mean() - small[..., 0].mean() > 25 and sum(b is not None for b in _skill_icons(img)) >= 3:
        return "skills"                              # blue backdrop with gold-framed skill icons
    if cyan_frac(img, (0.957, 0.016, 0.992, 0.021)) > 0.6 or cyan_frac(img, (0.957, 0.044, 0.992, 0.049)) > 0.6:
        return "talents"                             # RESET button, top right (the SKILLS view has one too)
    if small.mean() < 45:
        return "dark"
    return "other"


# ----------------------------------------------------------- pre-battle
def find_labels(img, side):
    """Locate the name plates: bright name text in the side's exact UI colour with a white
    bar to its left. -> list of (x0, y0, x1, y1) of the name line."""
    a = np.asarray(img).astype(np.int16)
    W = img.size[0]
    x_lo, x_hi = (0, W // 2) if side == "mine" else (W // 2, W)
    sub = a[:, x_lo:x_hi]
    mask = np.abs(sub - np.array(NAME_COLOUR[side])).max(axis=2) <= 40
    dil = ndi.binary_dilation(mask, structure=np.ones((3, 11), bool))
    lab, _ = ndi.label(dil)
    out = []
    for sl in ndi.find_objects(lab):
        ys, xs = sl
        w, h = xs.stop - xs.start, ys.stop - ys.start
        if 40 <= w <= 330 and 10 <= h <= 22 and int(mask[sl].sum()) >= 150:
            gx0 = xs.start + x_lo
            bar = a[max(0, ys.start - 4): ys.start + 30, max(0, gx0 - 18): max(1, gx0 - 8)]
            if bar.size and float((bar.min(axis=2) >= 215).mean(axis=0).max()) > 0.6:
                out.append((gx0, ys.start, xs.stop + x_lo, ys.stop))
    return sorted(out, key=lambda t: (t[1], t[0]))


def _label_ink(img, box, side):
    sub = np.asarray(img.crop(box)).astype(int)
    if side == "mine":
        return (sub[..., 1] > 150) & (sub[..., 0] < 130) & (sub[..., 2] < 90)
    return ((sub[..., 0] > 170) & (sub[..., 1] < 140) & (sub[..., 2] < 140)
            & ((sub[..., 0] - sub[..., 1]) > 90))


def cell_for(side, cx, cy):
    """Nearest grid cell. -> (col, row, distance)"""
    L, best = LATTICE[side], None
    for c in (0, 1):
        for r in range(4):
            d = ((cx - L["x"][c][r]) ** 2 + (cy - L["y"][r]) ** 2) ** 0.5
            if best is None or d < best[0]:
                best = (d, c, r)
    return best[1], best[2], best[0]


def read_header(img):
    """Both players' power from the top bar (best effort)."""
    a = lambda box, fn: np.asarray(img.crop(box)).astype(int)
    my = a((700, 36, 870, 58), None)
    en = a((1058, 36, 1230, 58), None)
    my_m = (my[..., 2] > 200) & (my[..., 0] < 170) & (my[..., 1] > 140)
    en_m = (en[..., 0] > 200) & (en[..., 1] < 140) & (en[..., 2] < 140)

    def num(mask):
        t = _ocr(mask, psm=7, whitelist="0123456789,")
        return int(t.replace(",", "")) if _NUM.match(t) else None
    return {"my_power": num(my_m), "opp_power": num(en_m)}


def label_boxes(img):
    """Name-plate positions on both sides. Cheap (no OCR): used to notice a march being moved."""
    img = normalize(img)
    return {side: find_labels(img, side) for side in ("mine", "enemy")}


def parse_prebattle(img, lib=None, known=(), boxes=None):
    """Both lineups with grid positions and troop counts."""
    img = normalize(img)
    known = list(known)
    boxes = boxes or label_boxes(img)
    ocr_available()                                  # set OCR up once, before the threads start

    def read(job):
        side, (x0, y0, x1, y1) = job
        hx, hy = x0 - 50, y0 + 12
        col, row, dist = cell_for(side, hx, hy)
        flags = []
        raw = _ocr(_best_cluster(_label_ink(img, (x0 - 2, y0 - 2, x1 + 4, y1 + 2), side), gap=16), psm=7)
        # two independent masks vote: brightness (works on the dark night map) and text colour
        cbox = (x0 - 6, y0 + 17, x0 + 100, y0 + 38)
        troops = _read_count(np.asarray(img.crop(cbox)).max(2) >= 150, _label_ink(img, cbox, side))
        if troops is None and ocr_available():
            flags.append("troop count unreadable")
        elif troops is not None and troops < 40000:
            flags.append(f"troop count {troops:,} looks too low")
        pname, sim = None, 0.0
        if lib is not None:
            pname, sim, _ = lib.identify(img, hx, hy, CTX_SIZE["pre"])
        name, src, nflags = resolve_name(raw, pname, known)
        if name in priors.PRIME_BASES and is_prime(img, hx, hy):
            name += " Prime"
        flags += nflags
        if dist > 80:
            flags.append("unusual grid position")
        return {"side": side, "col": col, "row": row, "name": name, "name_src": src, "name_raw": raw,
                "troops": troops, "hex": (hx, hy), "portrait_sim": round(sim, 2), "flags": flags}

    out = {"mine": [], "enemy": [], "flags": [], "boxes": boxes,
           "header": read_header(img) if ocr_available() else {}}
    jobs = [(side, b) for side in ("mine", "enemy") for b in boxes[side]]
    with ThreadPoolExecutor(8) as pool:              # each name plate is read independently
        for m in pool.map(read, jobs):
            if any(o["col"] == m["col"] and o["row"] == m["row"] for o in out[m["side"]]):
                m["flags"].append("two marches in one cell")
            out[m["side"]].append(m)
    if not out["mine"] or not out["enemy"]:
        out["flags"].append("could not find both lineups")
    return out


# -------------------------------------------------------------- result
def _delta(img, box):
    """Star change next to a player's name: sign from the colour, size from the digits."""
    s = np.asarray(img.crop(box)).astype(int)
    green = (s[..., 1] > 200) & (s[..., 0] < 100) & (s[..., 2] < 100)
    red = (s[..., 0] > 200) & (s[..., 1] < 100) & (s[..., 2] < 100)
    if green.sum() < 15 and red.sum() < 15:
        return None
    sign, mask = (1, green) if green.sum() >= red.sum() else (-1, red)
    # '+' and '-' stay in the whitelist: without them the engine turns a '+' into a '4'
    t = re.findall(r"\d+", _ocr(_best_cluster(mask, gap=10), psm=7, whitelist="+-0123456789"))
    return sign * int(t[0]) if t else None


def parse_result(img):
    """The VICTORY / DEFEAT screen. Returns None if this is not a result screen."""
    img = normalize(img)
    ocr_available()
    jobs = {f"banner{thr}": (lambda thr=thr: _ocr(_white(img, (640, 300, 1280, 410), thr, sat_max=255), psm=7, scale=2))
            for thr in (200, 230, 170)}
    jobs.update(
        mine=lambda: _delta(img, (808, 584, 870, 616)), opp=lambda: _delta(img, (1244, 584, 1306, 616)),
        rank=lambda: re.findall(r"\d+", _ocr(_white(img, (840, 420, 1090, 460), 200), psm=7, scale=4)),
        opp_name=lambda: _ocr(_white(img, (1155, 548, 1370, 575), 200, sat_max=255), psm=7, scale=3),
        my_stars=lambda: read_plain_int(img, (750, 584, 810, 616)),
        opp_stars=lambda: read_plain_int(img, (1186, 584, 1246, 616)))
    with ThreadPoolExecutor(len(jobs)) as pool:      # every read is its own OCR process: run them side by side
        got = dict(zip(jobs, pool.map(lambda f: f(), jobs.values())))
    up = " ".join(v for k, v in got.items() if k.startswith("banner")).upper()
    result = "win" if "VICT" in up else "loss" if ("DEFE" in up or "DEFEA" in up) else \
        "draw" if "DRAW" in up else None
    mine, opp, rank, opp_name = got["mine"], got["opp"], got["rank"], got["opp_name"]
    flags = []
    if result is None:
        if mine is None:
            return None                      # not a result screen
        result = "win" if mine > 0 else "loss" if mine < 0 else "draw"
        flags.append("result taken from the star change, banner unreadable")
    return {
        "result": result,
        "rank_before": int(rank[0]) if len(rank) >= 2 else None,
        "rank_after": int(rank[1]) if len(rank) >= 2 else None,
        "my_stars": got["my_stars"],
        "my_delta": mine,
        "opp_stars": got["opp_stars"],
        "opp_delta": opp,
        "opp_name": re.sub(r"\s+", " ", opp_name).strip(),
        "flags": flags,
    }


# --------------------------------------------------------------- stats
def assign_names(lib, img, cells, s, names):
    """Match each portrait to a distinct commander out of `names` (best overall fit)."""
    names = list(dict.fromkeys(names))
    S = np.full((len(cells), len(names)), -1.0)
    for i, (cx, cy) in enumerate(cells):
        sc = lib.scores(img, cx, cy, s)
        for j, n in enumerate(names):
            S[i, j] = sc.get(n, -1.0)
    r, c = linear_sum_assignment(-S)
    res = [(None, 0.0)] * len(cells)
    for i, j in zip(r, c):
        res[i] = (names[j], float(S[i, j]))
    return res


def parse_stats(img, lib=None, my_names=None, enemy_names=None, stash=False):
    """Per-commander units remaining / healed / kills for both sides."""
    img = normalize(img)
    out = {"mine": [], "enemy": [], "flags": []}
    for side, names in (("mine", my_names), ("enemy", enemy_names)):
        C = STATS_COLS[side]
        cells = [(C["x"], y + 5) for y in STATS_ROWS]
        ids = [(None, 0.0)] * 5
        if lib is not None and names:
            ids = assign_names(lib, img, cells, CTX_SIZE["stats"], names)
        elif lib is not None:
            ids = [lib.identify(img, cx, cy, CTX_SIZE["stats"], min_sim=0.45, min_margin=0.05)[:2]
                   for cx, cy in cells]
        keys = ("remaining", "healed", "kills")
        ocr_available()                              # set OCR up once, before the threads start
        with ThreadPoolExecutor(8) as pool:          # each read is its own OCR process: run them side by side
            nums = list(pool.map(lambda b: read_number(img, b)[0],
                                 [(C[k] - 50, y - 12, C[k] + 50, y + 12) for y in STATS_ROWS for k in keys]))
        for r, ((cx, cy), (name, sim), y) in enumerate(zip(cells, ids, STATS_ROWS)):
            row = {"name": name, "sim": round(sim, 2), "secondary": None}
            for c, key in enumerate(keys):
                v = nums[r * 3 + c]
                row[key] = v
                if v is None:
                    out["flags"].append(f"{side} {name}: {key} unreadable")
            if lib is not None:
                dx, dy = C["sec"]
                sname, ssim, _ = lib.identify(img, cx + dx, cy + dy, CTX_SIZE["sec"],
                                              min_sim=0.72, min_margin=0.12)
                row["secondary"] = sname
                if sname is None and stash:
                    lib.stash_unknown(img, cx + dx, cy + dy, CTX_SIZE["sec"], "sec")
            out[side].append(row)
    return out


# ----------------------------------------------------------- challenge
def find_strip_y(img, xs):
    """The enemy defence line-up is shown under whichever opponent is expanded; find its row."""
    a = np.asarray(img).astype(int)
    best, by = 0.0, None
    for y in range(440, 960, 3):
        sc = 0.0
        for x in xs:
            box = a[y - 24: y + 4, x - 18: x + 18]
            if box.size == 0:
                continue
            mx, mn = box.max(2), box.min(2)
            sat = (mx - mn) / np.maximum(mx, 1)
            sc += float(((sat > 0.55) & (mx > 110) & (box[..., 0] > 110)).mean())
        if sc > best:
            best, by = sc, y
    return (by, best / len(xs)) if by is not None else (None, 0.0)


def _read_level(img, x, y, k=1.0):
    """Commander level printed on the bottom of a hex (k = hex size relative to 66 px).
    Voted over a few vertical offsets."""
    votes = []
    for dy in (-2, 0, 2):
        s = np.asarray(img.crop((int(x - 11 * k), int(y + dy + 20 * k), int(x + 11 * k), int(y + dy + 40 * k)))).astype(int)
        for thr in (150, 170, 190):
            mask = (s.min(2) >= thr) & ((s.max(2) - s.min(2)) <= 70)
            if mask.sum() < 10:
                continue
            t = re.sub(r"\D", "", _ocr(_best_cluster(mask, gap=6), psm=8, whitelist="0123456789", scale=5))
            if t and 1 <= int(t) <= 60:
                votes.append(int(t))
    return votes


def parse_challenge(img, lib=None, stash=False):
    """The opponent line-up shown on the challenge list. -> dict or None if none is expanded."""
    img = normalize(img)
    mode = challenge_mode(img)
    if mode is None:
        return None
    L = CHALLENGE[mode]
    if mode == "rank":                               # strip height from the level digits (30 px above them)
        r, strength = level_row(img, L["x"])
        if strength < 150:
            return None                              # no row opened
        y, score = r - 30, strength / 300
    else:
        y, score = find_strip_y(img, L["x"])
        if y is None or score < 0.3:
            return None
    marches = []
    for i, x in enumerate(L["x"]):
        name, sim, sec = None, 0.0, None
        hx, hy, k = x, y, L["s"] / 66.0
        if lib is not None:
            name, sim, _ = lib.identify(img, x, y, L["s"], min_sim=0.8, min_margin=0.12, wide=True)
            if name:                       # the match tells us where the hex really is
                dx, dy, sc = lib.last_fit
                hx, hy, k = x + dx, y + dy, k * sc
            sx, sy, ss = hx + L["sec"][0] * k * 66 / L["s"], hy + L["sec"][1] * k * 66 / L["s"], 38 * k
            sec, _, _ = lib.identify(img, sx, sy, ss, min_sim=0.8, min_margin=0.12, wide=True)
            if stash and name is None:
                lib.stash_unknown(img, hx, hy, 66 * k, "chal")
            if stash and sec is None:
                lib.stash_unknown(img, sx, sy, ss, "sec")
        # expert: main portrait only; a secondary's thin frame cannot be judged, so it stays unknown
        marches.append({"idx": i, "name": name, "sim": round(sim, 2), "level": None, "secondary": sec,
                        "expert": is_expert(img, x, y, L["s"]),      # strip position: the face match centres on the face, not the frame
                        "_spots": ((hx, hy, k), (x, y, L["s"] / 66.0))})
    ocr_available()
    with ThreadPoolExecutor(10) as pool:             # 10 level reads of ~9 OCR calls each: side by side
        reads = list(pool.map(lambda sp: _read_level(img, *sp), [sp for m in marches for sp in m["_spots"]]))
    for i, m in enumerate(marches):
        # vote over the expected spot and the spot the portrait match found
        votes = reads[2 * i] + reads[2 * i + 1]
        two = [v for v in votes if v >= 10] or votes        # a clipped crop reads one digit of two
        m["level"] = Counter(two).most_common(1)[0][0] if two else None
        del m["_spots"]
    a = np.asarray(img).astype(int)

    def digits(box, banner=False):                   # white digits; the sword icon may add a stray digit
        s = a[box[1]:box[3], box[0]:box[2]]
        for thr in (200, 180, 160):
            if banner:       # leaderboard: your power is pale cream on the gold banner
                m = (s.min(2) >= thr - 75) & (s.max(2) >= thr + 15)
            else:
                m = (s.min(2) >= thr - 40) & (s.max(2) >= thr) & ((s.max(2) - s.min(2)) <= 90)
            t = _ocr(_best_cluster(m, gap=10), psm=7, whitelist="0123456789,")
            if _NUM.match(t) and len(t) >= 9:
                return re.sub(r"\D", "", t)
        return ""
    top, bottom = L["strip"]                         # the line-up as the game shows it: hexes, secondaries, levels
    s = L["s"]
    strip_box = (int(L["x"][0] - 0.8 * s), int(y - top * s), int(L["x"][-1] + 1.3 * s), int(y + bottom * s))
    return {"mode": mode, "strip_y": y, "strip_box": strip_box, "strip_score": round(score, 2), "marches": marches,
            "my_power_digits": digits(L.get("my_pw", (640, 338, 1000, 372)), banner=mode == "rank"),
            "opp_power_digits": digits((lambda b: (b[0], y + b[1], b[2], y + b[3]))(L.get("opp_pw", (640, -128, 940, -92))))}


# ----------------------------------------------------- commander screens
# Three views of one commander. Small fixed-position reads (skill digits on the main view, the
# mini gear diamond) proved unreliable on a live capture, so each fact comes from the view
# that prints it large:  main view -> level, stars, power;  SKILLS -> skill levels;
# the "?" popup of the gear view -> the gear's actual stat bonuses.
NAME_BOX = {"commander": (1480, 272, 1900, 320), "gearstats": (1480, 212, 1900, 260)}
SKILL_QUADS = [(250, 60, 760, 400), (1160, 60, 1700, 400), (200, 400, 700, 720), (1220, 380, 1720, 720)]


def commander_key(img, view="commander"):
    """Fingerprint of the commander's printed name. The 3D background is animated, so only the
    dark name text is used: it stays the same until another commander is opened."""
    m = np.asarray(normalize(img).crop(NAME_BOX[view])).astype(int).max(2) < 70
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((70, 8), Image.BOX)) > 60


def same_commander(a, b):
    """Two fingerprints of the same name differ in a few edge cells at most."""
    return a is not None and b is not None and float((a ^ b).mean()) < 0.06


def _read_name(img, view, known):
    dark = np.asarray(img.crop(NAME_BOX[view])).astype(int).max(2) < 70
    raw = _ocr(_best_cluster(dark, gap=30), psm=7)
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z' \-\.]", "", _ascii(raw))).strip()
    return fix_name(cleaned, known)[0] or (cleaned if len(cleaned) >= 3 else None)


def parse_commander(img, known=()):
    """Main commander view (key P in the city): name, level, stars, capacity, power."""
    img = normalize(img)
    a = np.asarray(img).astype(int)
    dark = lambda box: np.asarray(img.crop(box)).astype(int).max(2) < 70
    ocr_available()
    jobs = [lambda: _read_name(img, "commander", known),
            lambda: _ocr(_best_cluster(dark((1500, 418, 1640, 448)), gap=14), psm=7),
            lambda: _ocr(_best_cluster(dark((1500, 498, 1720, 528)), gap=14), psm=7),
            lambda: _ocr(_white(img, (985, 984, 1080, 1014), 215), psm=7, whitelist="0123456789,")]
    with ThreadPoolExecutor(4) as pool:
        name, lvl_t, cap_t, pow_t = [f.result() for f in [pool.submit(j) for j in jobs]]
    lvl = re.search(r"(\d+)\s*/\s*\d+", lvl_t)
    cap = re.sub(r"\D", "", cap_t)
    row = a[365:400, 1495:1815]
    cols = np.where(((row[..., 0] > 220) & (row[..., 1] > 170) & (row[..., 2] < 90)).any(0))[0]
    return {"name": name, "level": int(lvl.group(1)) if lvl else None,
            "stars": 1 + int((np.diff(cols) > 8).sum()) if cols.size else 0,
            "capacity": int(cap) if cap else None,
            "power": int(pow_t.replace(",", "")) if _NUM.match(pow_t) else None}


def _skill_icons(img):
    """The four skill icons on the SKILLS view, found by their gold frames. The selected skill
    is drawn larger and shifted, so positions are measured, not assumed. -> [(x0, y0, x1, y1) or None] * 4"""
    a = np.asarray(img).astype(int)
    out = []
    for q in SKILL_QUADS:
        s = a[q[1]:q[3], q[0]:q[2]]
        gold = (s[..., 0] > 200) & (s[..., 1] > 140) & (s[..., 2] < 90)
        lab, n = ndi.label(ndi.binary_dilation(gold, iterations=3))
        boxes = [(sl[1].start + q[0], sl[0].start + q[1], sl[1].stop + q[0], sl[0].stop + q[1]) for sl in ndi.find_objects(lab)]
        boxes = [b for b in boxes if b[2] - b[0] >= 100 and b[3] - b[1] >= 90]
        out.append(max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if boxes else None)
    return out


_DIGITS = None


def _match_digit(mask):
    """Closest skill-level digit from skill_digits.json (built from real screenshots). -> (digit, 0..1)"""
    global _DIGITS
    if _DIGITS is None:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_digits.json")) as fh:
                t = json.load(fh)
            tw, th = t["size"]
            norm = lambda v: (v - v.mean()) / (np.linalg.norm(v - v.mean()) + 1e-9)
            _DIGITS = (tw, th, [(d, norm(np.array([int(c) for c in bits], float))) for d, lst in t["digits"].items() for bits in lst])
        except (OSError, ValueError, KeyError):
            _DIGITS = (12, 16, [])
    tw, th, temps = _DIGITS
    v = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize((tw, th), Image.BOX)).astype(float).ravel() / 255
    v = (v - v.mean()) / (np.linalg.norm(v - v.mean()) + 1e-9)
    best = max(((float(t @ v), d) for d, t in temps), default=(0.0, "?"))
    return best[1], best[0]


def parse_skills(img):
    """SKILLS view: the four skill levels and whether the expertise skill is unlocked.
    -> {"skills": "5351", "expert": bool} or None when a level cannot be read.
    Each level is the white digit in the lower right of its icon."""
    img = normalize(img)
    ocr_available()
    a = np.asarray(img).astype(int)

    def level(box):
        if box is None:
            return "?"
        x0, y0, x1, y1 = box
        w = x1 - x0
        # the digit sits in the lower right; scale by the icon's width (its height is cut by the lock badge)
        X0, Y0, X1, Y1 = int(x0 + 0.45 * w), int(y0 + 0.40 * w), int(x1 + 0.35 * w), int(y0 + 1.15 * w)
        sub = a[max(0, Y0):Y1, max(0, X0):X1]
        lab, _ = ndi.label((sub.min(2) >= 225) & ((sub.max(2) - sub.min(2)) <= 30))
        cands = []
        for i, sl in enumerate(ndi.find_objects(lab), 1):
            ch, cw = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if 0.14 * w <= ch <= 0.25 * w and cw >= 0.05 * w and ch / cw >= 1.15:     # digit-shaped: not artwork, not the lock
                cands.append((ch * cw, lab[sl] == i))
        for _, m in sorted(cands, key=lambda t: -t[0]):
            d, score = _match_digit(m)
            if score >= 0.8:
                return d
            t = _ocr(np.pad(m, 3), psm=10, whitelist="12345", scale=3)    # a digit with no template yet (a 4)
            if t in list("12345"):
                return t
        return "?"
    with ThreadPoolExecutor(4) as pool:
        skills = "".join(pool.map(level, _skill_icons(img)))
    if "?" in skills:
        return None
    centre = np.asarray(img.crop((912, 610, 1004, 706))).astype(int)      # the expertise icon
    return {"skills": skills, "expert": skills == "5555" and float(centre.max(2).mean()) > 120}


def parse_gearstats(img, known=()):
    """The "Equipment Attributes" popup (gear view, "?" button): every stat bonus the gear gives.
    -> {"name": ..., "stats": {"Infantry Attack": 8.0, ...}}"""
    img = normalize(img)
    ocr_available()
    a = np.asarray(img).astype(int)
    white = (a[285:900, 1100:1450].min(2) > 235).mean(axis=1) > 0.5
    bottom = 285 + (int(np.where(white)[0].max()) if white.any() else 385)
    panel = img.crop((1095, 285, 1455, bottom))
    text = pytesseract.image_to_string(panel.resize((panel.width * 2, panel.height * 2), Image.LANCZOS), config="--psm 6")
    stats = {}
    for line in text.splitlines():
        m = re.search(r"([A-Z][A-Za-z]+(?: [A-Za-z]+)*)\s*\+\s*(\d+(?:\.\d+)?)", line)
        if m:
            words = m.group(1).split()
            while words and len(words[0]) <= 2:          # the line's icon, read as a stray letter or two
                words.pop(0)
            if words:
                stats[" ".join(words)] = float(m.group(2))
    return {"name": _read_name(img, "gearstats", known), "stats": stats}


# ------------------------------------------------------------------ CLI
def describe(path, lib=None, known=()):
    img = Image.open(path)
    kind = classify(img)
    print(f"{path}: screen = {kind}   (OCR {'ready' if ocr_available() else 'NOT available'})")
    if kind == "prebattle":
        r = parse_prebattle(img, lib, known)
    elif kind == "stats":
        r = parse_stats(img, lib)
    elif kind == "challenge":
        r = parse_challenge(img, lib)
    elif kind == "dark":
        r = parse_result(img)
    elif kind == "commander":
        r = parse_commander(img, known)
    elif kind == "skills":
        r = parse_skills(img)
    elif kind == "gearstats":
        r = parse_gearstats(img, known)
    else:
        r = None
    print(json.dumps(r, indent=1, default=str))


if __name__ == "__main__":
    import priors
    library = portraits.Library("portraits")
    names = list(priors.KNOWN_NAMES) + library.known_names()
    for p in sys.argv[1:]:
        describe(p, library, names)
