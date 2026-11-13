# Sunset Canyon helper: notes for Claude Code

A local Windows tool for Rise of Kingdoms (PC client). It watches the screen, logs every Sunset
Canyon and Lost Canyon fight into SQLite, reads commander data, and advises on the status bar.
Started in a claude.ai chat (Nov 2026); this file carries over what that chat decided.

## Run and test

- `python app.py` starts the web app (http://127.0.0.1:8765), the screen watcher and the status bar.
  `Start Sunset Helper.bat` does the same without a console. Right-click the bar to quit.
- Tests, all must pass before handing anything over:
  `python smoke_test.py` (database and analysis), `python test_vision.py` (screen reader on
  `testshots/`), `python test_e2e.py` (screenshots fed through the watcher, then every web page).
- `python vision.py some_screenshot.png` prints what the reader sees on one screen.
- Bump `BUILD` in `watcher.py` on every change: the idle bar shows it, which is how the user
  confirms a restart picked up the new code.
- Releasing to friends: raise the number in `version.txt`, commit, push to GitHub (ask the user first:
  pushing publishes). Their bar then says "Update available". The repo is public: `.gitignore` keeps out
  user data, `shared.json`, portraits (game art) and testshots (other players' names).

## Files

| File | Job |
|---|---|
| `vision.py` | Screen reader. Everything is measured at 1920x1080; input is rescaled first. |
| `watcher.py` | Polls the screen ~1/s, state machine per screen type, writes fights, builds the bar text (`hint`). |
| `overlay.py` | Status bar (tkinter). First line = state colour; further lines = suggestions in blue. |
| `engine.py` | Analysis: win chance, formation model, positioning rules, experiments, Report. |
| `db.py` | SQLite schema; columns are only ever added (`ADDED`), migrations and data repairs run at start. |
| `portraits.py` | Learned commander faces (`portraits/<name>/`), used where no name is printed. |
| `priors.py` | Seed data: roles, grades, known names (spelling fixes), guide pairings, Prime commanders. |
| `app.py` | Web pages. |
| `sync.py` | Sharing with friends: pushes finished fights to one Supabase table, pulls everyone's into `shared_fights`. |
| `updater.py` | Hourly check of `version.txt` on GitHub (`REPO`); "Update now" on Home installs the repo zip and restarts. |
| `make_friend_copy.py` | Builds the zip for friends (code, portraits, shared.json; no user data). |
| `skill_digits.json` | Templates of the skill-level digits 1, 2, 3, 5 (no 4 sample yet). |

User data, never overwrite: `rok_canyon.db`, `portraits/`, `captures/`, `gear.json`, `shared.json`.

## Decisions (do not undo without asking)

- **Only show what is proven on the user's own fights.** The win chance and the formation model
  are re-tested by leave-one-out after every fight and used only if they beat the plain win rate
  (`engine.win_model`, `engine.formation_model`). Troop ratio was tested and predicts nothing.
  As of 44 fights: power + enemy commanders passes; positions help ~1.9% after controlling for power.
  Secondaries (your pairings, their secondaries) are candidates in both models too; as of 43 fights they
  do not pass, so they are not used yet. Impossible secondaries (a commander twice in a line-up) are cleared.
- **Never correct a fight from a saved JPEG**: re-reading captures is less reliable than the live
  read (compression turned 92,000 into 32,000).
- **Wrong data is worse than none.** Unreliable reads were removed rather than guessed:
  skill digits and gear rarity on the main commander view, secondary-commander expertise.
- Joan of Arc is a tank (with Matilda of Flanders as secondary). Roles drive the column rules.
- Sunset and Lost Canyon share mechanics: data is pooled, `mode` is only a label
  (Lost Canyon results show no rank or star change).
- Equipment and talents matter only for the primary commander.
- Sharing (Nov 14): free Supabase, friends install Python themselves, pooled stats only. Only a random
  player id is sent, never player or opponent names. Shared fights are insert-only (no update/delete policy),
  so a fight goes up once its stats are in, or 30 min after saving. Shared fights are not in the models yet:
  when they are, they may only be used if they help on the user's OWN fights (leave-one-out).
- Expertise = pale silver hex frame (main portraits only).
- Bar on the challenge list: "Scanned n/5 | win ~x%" coloured by the chance (green >=55%, red <=45%), the
  scanned line-up strip cut from the screen underneath (not learned portraits: those show stale secondaries), and a white flash on each newly scanned opponent. Expertise and levels: stored, not shown.
- Slow reads (challenge, pre-battle, result, stats) run on a worker thread in order (`Watcher._submit`); the bar
  says "captured" as soon as the frame is taken. Polls every 0.5 s. Each OCR call is a Tesseract process (~0.12 s):
  run independent reads side by side.

## Where each fact comes from

- Pre-battle: both line-ups, grid cells (2 columns x 4 rows; column 0 = front), troop counts, powers.
- Result screen: win/loss, rank and star change. Stats screen: remaining, kills, healed, secondaries.
- Challenge list (Sunset and Lost Canyon layouts): opponent line-up, levels, expertise, both powers;
  saved to `scouted` and linked to the fight if it is fought.
- Commander view (key P): level, stars, power. SKILLS view: skill levels. Gear "?" popup: gear stats.
  TALENTS: kept as a picture only (totals too small to read).

## Open items

- A skill digit 4 has no template; when one appears, add it to `skill_digits.json`.
- Challenge-list expertise over-counts: user saw 2 flagged where 1 was expertised (Nov 13). Needs a full
  1920x1080 screenshot of that list in `testshots/` to fix.
- Your secondaries are missing for 76 marches (faces not known when the stats screen was read).
- Fights 2, 11, 14, 37 and 43 are flagged in History (cleared troop counts, missing marches).
- Defense fights: the only source is the Sunset Canyon HISTORY list (attacks and defenses mixed: time ago,
  opponent, power, VICTORY/DEFEAT, star change). Attacks match logged fights by exact opponent power.
  Waiting for screenshots of an expanded row (chevron) and its stats icon before building a reader.
- Ideas not built: expected stars per opponent, a full line-up builder from the roster,
  reading the gear item identity, defense line-up advice.
