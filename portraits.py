"""Portrait library.

The pre-battle screen prints every commander's name next to the portrait. That lets the
tool learn what each commander looks like, and then recognise the same commander on
screens that show portraits only (the challenge list and the stats screen).

Learned portraits are plain PNG files under portraits/<Commander name>/, so you can look
at them, delete bad ones, or rename a folder. Portraits it could not identify are kept in
portraits/_unknown/ for the Teach page.
"""
import hashlib
import os
import re
import shutil

import numpy as np
from PIL import Image

FACE = (20, 12)
# hex width in pixels (at 1920x1080) for each screen context
CTX_SIZE = {"pre": 62, "chal": 66, "stats": 56, "chalsec": 38, "sec": 28}
SHIFTS = [(dx, dy) for dx in (-3, 0, 3) for dy in (-3, 0, 3)]
MAX_PER_CTX = 6


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9 '\-\.]", "_", name).strip() or "unnamed"


def face_vec(img, cx, cy, s):
    """Normalised pixel vector of the upper-centre 'face' area of a hex of width s."""
    box = (cx - 0.30 * s, cy - 0.36 * s, cx + 0.30 * s, cy + 0.06 * s)
    t = img.crop(tuple(int(round(v)) for v in box)).resize(FACE, Image.LANCZOS)
    a = np.asarray(t, dtype=float).reshape(-1)
    a = a - a.mean()
    return a / (np.linalg.norm(a) + 1e-9)


def _crop_square(img, cx, cy, s):
    side = int(round(1.25 * s))
    x0 = int(round(cx - side / 2.0))
    y0 = int(round(cy - side / 2.0))
    return img.crop((x0, y0, x0 + side, y0 + side)), side


def face_file(root, name):
    """One learned picture of this commander to show (web pages, status bar), or "" if none yet."""
    import difflib
    if not name or not os.path.isdir(root):
        return ""
    d = os.path.join(root, safe_name(name))
    if not os.path.isdir(d):                    # a folder saved under an OCR slip ("Matilda Of Flander")
        key = lambda n: n.lower().replace(" ", "")
        near = [f for f in os.listdir(root) if difflib.SequenceMatcher(None, key(f), key(name)).ratio() >= 0.9]
        if not near:
            return ""
        d = os.path.join(root, near[0])
    files = sorted(f for f in os.listdir(d) if f.endswith(".png"))
    best = [f for f in files if f.startswith("chal_")] or [f for f in files if f.startswith("pre_")] or files
    return os.path.join(d, best[0]) if best else ""


class Library:
    def __init__(self, root="portraits"):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.reload()

    # ---------------------------------------------------------------- loading
    def reload(self):
        self.names, self.ctxs, vecs = [], [], []
        for name in sorted(os.listdir(self.root)):
            d = os.path.join(self.root, name)
            if name.startswith("_") or not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if not f.lower().endswith(".png"):
                    continue
                try:
                    im = Image.open(os.path.join(d, f)).convert("RGB")
                except Exception:
                    continue
                w, h = im.size
                self.names.append(name)
                self.ctxs.append(f.split("_")[0])
                vecs.append(face_vec(im, w / 2.0, h / 2.0, w / 1.25))
        self.M = np.array(vecs) if vecs else np.zeros((0, FACE[0] * FACE[1] * 3))

    def known_names(self):
        return sorted(set(self.names))

    def counts(self):
        out = {}
        for n in self.names:
            out[n] = out.get(n, 0) + 1
        return dict(sorted(out.items()))

    # --------------------------------------------------------------- matching
    def scores(self, img, cx, cy, s, wide=False):
        """Best similarity per commander name for the hex at (cx, cy).
        wide=True also tries positions up to 15 px away and up to 20% larger: screens that
        place portraits at fixed spots drift when the game window has a border or title bar.
        self.last_fit = (dx, dy, scale) of the best match."""
        self.last_fit = (0, 0, 1.0)
        if not len(self.names):
            return {}
        tries = [(dx, dy, 1.0) for dx, dy in SHIFTS]
        if wide:
            tries = [(dx, dy, k) for k in (1.0, 1.1, 1.2) for dx in range(-15, 16, 3) for dy in range(-15, 16, 3)]
        q = np.stack([face_vec(img, cx + dx, cy + dy, s * k) for dx, dy, k in tries], axis=1)
        all_sims = self.M @ q
        self.last_fit = tries[int(all_sims.max(axis=0).argmax())]
        sims = all_sims.max(axis=1)
        best = {}
        for n, v in zip(self.names, sims):
            if v > best.get(n, -1.0):
                best[n] = float(v)
        return best

    def identify(self, img, cx, cy, s, min_sim=0.6, min_margin=0.08, restrict=None, wide=False):
        """-> (name or None, similarity, margin). None when not confident."""
        sc = self.scores(img, cx, cy, s, wide)
        if restrict is not None:
            sc = {n: v for n, v in sc.items() if n in restrict}
        if not sc:
            return None, 0.0, 0.0
        ranked = sorted(sc.items(), key=lambda t: -t[1])
        top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = top[1] - second
        if top[1] >= min_sim and margin >= min_margin:
            return top[0], top[1], margin
        return None, top[1], margin

    # --------------------------------------------------------------- learning
    def add(self, name, img, cx, cy, s, ctx):
        name = safe_name(name)
        crop, side = _crop_square(img, cx, cy, s)
        v = face_vec(crop, side / 2.0, side / 2.0, side / 1.25)
        idx = [i for i, (n, c) in enumerate(zip(self.names, self.ctxs)) if n == name and c == ctx]
        if idx and float((self.M[idx] @ v).max()) >= 0.985:
            return False
        if len(idx) >= MAX_PER_CTX:
            return False
        d = os.path.join(self.root, name)
        os.makedirs(d, exist_ok=True)
        h = hashlib.md5(crop.tobytes()).hexdigest()[:10]
        crop.save(os.path.join(d, f"{ctx}_{h}.png"))
        self.names.append(name)
        self.ctxs.append(ctx)
        self.M = np.vstack([self.M, v]) if len(self.M) else v[None, :]
        return True

    # ---------------------------------------------------- unknown portraits
    def _unknown_dir(self):
        d = os.path.join(self.root, "_unknown")
        os.makedirs(d, exist_ok=True)
        return d

    def stash_unknown(self, img, cx, cy, s, ctx):
        crop, side = _crop_square(img, cx, cy, s)
        v = face_vec(crop, side / 2.0, side / 2.0, side / 1.25)
        d = self._unknown_dir()
        for f in os.listdir(d):
            try:
                im = Image.open(os.path.join(d, f)).convert("RGB")
            except Exception:
                continue
            w, h = im.size
            if float(face_vec(im, w / 2.0, h / 2.0, w / 1.25) @ v) >= 0.9:
                return False
        h = hashlib.md5(crop.tobytes()).hexdigest()[:10]
        crop.save(os.path.join(d, f"{ctx}_{h}.png"))
        return True

    def prune_unknown(self):
        """Drop queued faces that the library can recognise by now."""
        d, n = self._unknown_dir(), 0
        for f in os.listdir(d):
            try:
                im = Image.open(os.path.join(d, f)).convert("RGB")
            except Exception:
                continue
            w, h = im.size
            if self.identify(im, w / 2.0, h / 2.0, w / 1.25)[0]:
                os.remove(os.path.join(d, f))
                n += 1
        return n

    def unknown_files(self):
        d = self._unknown_dir()
        return sorted(f for f in os.listdir(d) if f.lower().endswith(".png"))

    def name_unknown(self, filename, name):
        src = os.path.join(self._unknown_dir(), os.path.basename(filename))
        if not os.path.exists(src):
            return False
        dst_dir = os.path.join(self.root, safe_name(name))
        os.makedirs(dst_dir, exist_ok=True)
        shutil.move(src, os.path.join(dst_dir, os.path.basename(src)))
        self.reload()
        self.prune_unknown()      # other queued copies of the same face are no longer needed
        return True

    def discard_unknown(self, filename):
        p = os.path.join(self._unknown_dir(), os.path.basename(filename))
        if os.path.exists(p):
            os.remove(p)

    def remove_commander(self, name):
        d = os.path.join(self.root, safe_name(name))
        if os.path.isdir(d):
            shutil.rmtree(d)
            self.reload()
