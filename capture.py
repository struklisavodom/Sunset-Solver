"""Optional screen scanning. Everything here degrades gracefully if the libraries are
missing; the rest of the app does not need it.

Needs (install on your own computer):
    pip install mss pillow pytesseract      # plus the Tesseract OCR program itself
or  pip install mss pillow easyocr

This is a first, text-only version: it grabs the screen, reads the text, and matches
it against known commander names. Once I see your actual battle screen we can crop to
the exact regions and read levels, skills and positions properly (or match portraits).
"""
import difflib
import re


def grab(monitor=1):
    try:
        import mss
        from PIL import Image
    except ImportError:
        return None, "Screen capture needs: pip install mss pillow"
    with mss.mss() as sct:
        mons = sct.monitors
        shot = sct.grab(mons[min(monitor, len(mons) - 1)])
        return Image.frombytes("RGB", shot.size, shot.rgb), ""


def read_text(img):
    try:
        import pytesseract
        return pytesseract.image_to_string(img), ""
    except Exception:
        pass
    try:
        import easyocr
        import numpy as np
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        return "\n".join(reader.readtext(np.array(img), detail=0)), ""
    except Exception:
        return "", "No OCR engine found. Install pytesseract (plus Tesseract) or easyocr."


def match_commanders(text, names, cutoff=0.82):
    """Fuzzy-find known commander names inside OCR text."""
    words = re.findall(r"[A-Za-z'\-]+", text)
    low = [w.lower() for w in words]
    found = []
    for name in names:
        parts = name.lower().split()
        n = len(parts)
        for i in range(0, max(0, len(low) - n + 1)):
            window = " ".join(low[i:i + n])
            if difflib.SequenceMatcher(None, window, name.lower()).ratio() >= cutoff:
                found.append(name)
                break
    return found


def scan(names):
    img, err = grab()
    if img is None:
        return {"error": err}
    text, err = read_text(img)
    if err:
        return {"error": err}
    return {"text": text, "commanders": match_commanders(text, names)}
