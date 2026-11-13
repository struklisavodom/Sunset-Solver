"""Update notice and one-click update from the public GitHub repo. Standard library only.

version.txt holds a whole number; raise it with every release you push. Each copy compares its own
version.txt with the one on GitHub about once an hour; "Update" downloads the repo as a zip, copies
the program files over this folder and restarts the app. User data is never touched (and is not
in the repo anyway): rok_canyon.db, captures/, gear.json, shared.json, portraits/.
"""
import io
import os
import subprocess
import sys
import time
import urllib.request
import zipfile

REPO = "struklisavodom/Sunset-Solver"   # "owner/name" on GitHub; empty = no update checks
BRANCH = "main"
HERE = os.path.dirname(os.path.abspath(__file__))
KEEP = ("rok_canyon.db", "captures/", "gear.json", "shared.json", "portraits/", "testshots/")
STATUS = {"local": None, "remote": None, "available": False, "error": ""}


def local_version():
    try:
        with open(os.path.join(HERE, "version.txt"), encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return 0


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "sunset-helper-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check():
    STATUS["local"] = local_version()
    if not REPO:
        return STATUS
    try:
        remote = int(_get(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/version.txt?t={int(time.time())}").decode().strip())
        STATUS.update(remote=remote, available=remote > STATUS["local"], error="")
    except Exception as e:          # offline: try again later
        STATUS["error"] = f"{type(e).__name__}: {e}"
    return STATUS


def run_forever(interval=3600):
    while True:
        check()
        time.sleep(interval)


def install(data, dest=HERE):
    """Copy the program files from a GitHub archive (bytes) into dest. -> number of files written"""
    n = 0
    root = os.path.realpath(dest)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""     # strip "<repo>-main/"
            if not rel or info.is_dir() or rel.startswith(KEEP) or rel in KEEP:
                continue
            target = os.path.realpath(os.path.join(root, rel))
            if not target.startswith(root + os.sep):       # never write outside the app folder
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(z.read(info))
            n += 1
    return n


def update_and_restart():
    """Download, install, start the new version (it asks this copy to quit, as on any start)."""
    data = _get(f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip", timeout=60)
    install(data)
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    subprocess.Popen([exe if os.path.isfile(exe) else sys.executable, os.path.join(HERE, "app.py"), "--no-browser"], cwd=HERE)
