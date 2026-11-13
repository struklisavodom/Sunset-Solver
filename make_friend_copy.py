"""Builds "Sunset Helper for friends.zip": the program, the learned portraits and shared.json.
Your own data stays out: rok_canyon.db, captures/, gear.json.   Run:  python make_friend_copy.py"""
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Sunset Helper for friends.zip")
SKIP_DIRS = {"captures", "__pycache__", ".claude"}
SKIP_FILES = {"rok_canyon.db", "gear.json", "CLAUDE.md", os.path.basename(OUT)}


def files():
    for root, dirs, names in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("_unknown")]
        for n in names:
            if n in SKIP_FILES or n.endswith((".db", ".db-journal", ".pyc")):
                continue
            yield os.path.join(root, n)


def main():
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files():
            z.write(f, os.path.join("Sunset Helper", os.path.relpath(f, HERE)))
    names = zipfile.ZipFile(OUT).namelist()
    assert not any(n.endswith(("rok_canyon.db", "gear.json")) or "/captures/" in n for n in names)
    print(f"Wrote {OUT} ({len(names)} files)" + ("" if any(n.endswith("shared.json") for n in names)
                                                  else "\nNo shared.json yet: your friends' copies will not share until you add it."))


if __name__ == "__main__":
    main()
