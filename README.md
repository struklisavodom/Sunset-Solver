# Sunset Canyon helper

A local tool for Rise of Kingdoms (PC client). It watches your screen, logs every Sunset
Canyon fight by itself, and suggests lineups that improve as your log grows.
Everything stays on your computer: one database file (`rok_canyon.db`), learned portraits
(`portraits/`) and a screenshot per logged fight (`captures/`).

## Install (once)

1. Python 3.9 or newer from python.org (tick "Add to PATH").
2. In a terminal, in this folder:

       pip install pillow numpy scipy mss pytesseract

3. Tesseract OCR, the program that reads the text on screen. On Windows, install it from
   https://github.com/UB-Mannheim/tesseract/wiki and keep the default folder
   (`C:\Program Files\Tesseract-OCR`). If you install it elsewhere, set the environment
   variable `TESSERACT_CMD` to the full path of `tesseract.exe`.

Check the install with the bundled screenshots:

    python test_vision.py        (should end with ALL CHECKS PASSED)

## Run

Double-click **Start Sunset Helper.bat**. No console window opens; the status bar appears in the
bottom-left corner. Double-click the bar to open the web pages, right-click it to quit.

For a taskbar button: run **Create taskbar shortcut.bat** once, then right-click the new
"Sunset Canyon Helper" icon on your Desktop and choose "Pin to taskbar".

(`python app.py` in a terminal still works and shows error messages if something is wrong.)

Updating: the `.py` files are replaced in place; quit (right-click the bar) and start again.
While idle the bar shows the build time, so you can tell the restart took effect.

## Using it

1. **Auto-log**: press Start, then play. The game must be visible on the chosen monitor,
   full screen or as a 16:9 window (enter the window's game area under Capture settings).
   The picture under "What I see" should show the game.
2. Each fight is saved from three screens:
   - pre-battle screen: both lineups, grid positions, troop counts
   - VICTORY / DEFEAT screen: result, rank and star change
   - STATS screen (optional, tap STATS after a fight): units left, kills, healing, secondary commanders
4. **Teach portraits**: faces seen without a printed name (mostly secondary commanders) wait
   here. Name each one once.
5. **History**: every fight. Entries marked "check" had something the reader was unsure of;
   open edit, fix, save.
6. **Report**: which of your commanders do the damage, which is the weak link, and which enemy
   commanders hurt you most. After every fifth fight the bar shows the top tip.
7. **Commanders**: troop type and role per commander (drives the positioning advice). Your roster
   fills itself from the commanders you field.

Tip: keep "Skip Battle" either on or off as you like, both work. Tapping STATS after a fight
gives the tool much better data (how decisively each march won or lost).

## Sharing with friends

Everyone keeps their own database; finished fights are also uploaded to one shared Supabase table
and everyone's fights are pooled on the **Shared** page. Only a random player id is sent, never
player or opponent names.

Setup (one person, once): follow the steps on the **Shared** page (free Supabase project, one SQL
script, then `shared.json` with the project URL and anon key). Then run

    python make_friend_copy.py

and send **Sunset Helper for friends.zip**. It holds the program, the learned portraits and
`shared.json`, but not your database, captures or gear.

Friends: unzip, do the Install steps above, start **Start Sunset Helper.bat**.

## The status bar (overlay)

A small bar sits in the bottom-left corner of your screen while the app runs:

- orange "Reading ..., wait": the screen is still being read
- green "Line-ups read. OK to start": safe to press OK (move marches first if you like; it re-reads)
- green "Battle #N saved. Continue": the result is stored
- on the challenge list and pre-battle screen it also shows a rough win chance

The win chance starts from the troop (or level) ratio and shifts toward your own record
against line-ups sharing commanders with this one. With few logged fights it is a rough guide.
The bar cannot draw over exclusive full screen: run the game windowed or borderless. Drag it
to move it. Start with `python app.py --no-overlay` to turn it off.

## Where to invest (Report)

Built from the fight log, Sunset and Lost Canyon pooled. Damage is kills divided by the march's
own troops; troops left is the share still standing. Both need the STATS screen, so tap STATS
after fights. Equipment comes from `gear.json` in this folder (rarity per slot for each primary
commander; secondaries' gear does not count in battle). Edit that file when you change gear.

## Scouting and expertise

- Auto-log starts with the app; there is no Start button to remember.
- Every opponent line-up you open on the challenge list is remembered, fought or not. The
  Report page shows which commanders and pairings opponents field most. Opening the arrows of
  higher-ranked players is the quickest way to teach the tool the strong line-ups.
- Expertised commanders (pale metallic portrait frame) are detected on the challenge list,
  shown on the bar, and counted as stronger in the win chance.
- In History, edit lets you correct names, lanes and troop counts.

## Positioning advice

Once the pre-battle line-ups are read, the bar adds what to move. Rules, in order:

1. Roles: tanks in the front column, area damage and support behind (Commanders page).
2. At least two marches in front.
3. Against this enemy: a march attacks the enemy directly facing it first (same row), then the
   nearest. So a single-target nuker is put opposite their tank, and a back-column march with
   no front march in its row gets called out when an enemy faces that row.
4. Your own log: a commander that clearly did better in the other column.

Rule 3 comes from Sunset Canyon guides (AllClash, riseofkingdomsguides). Ranges and skill
shapes are not modelled.

## Commander data

Look at a commander in the game (key P) and the tool stores what each view prints large:

| View | What is stored |
|---|---|
| Main view | level, stars, unit capacity, power |
| SKILLS | the four skill levels, and whether the expertise skill is unlocked |
| Gear view, then the "?" button | every stat bonus the gear gives (Infantry Attack +8%, ...) |
| TALENTS | a picture of the tree (the point totals are too small to read reliably) |

Open the main view first: SKILLS and TALENTS show no name, so they are filed under the commander
you opened just before. The bar confirms each read; everything is listed on **My commanders**.
Earlier versions read skills and gear rarity from small icons on the main view; those reads were
unreliable and that data has been cleared.

## Learning from your fights

Everything the bar says about your chances and your formation is tested on your own fights: a
model is used only when it predicts fights it had not seen better than your plain win rate does.
Both are re-tested after every fight; the Home page shows what is currently in use.

- **Win chance:** candidates are the opponent's power relative to yours, the enemy commanders,
  and both together. With 44 fights, "power and enemy commanders" passed. Powers are read on the
  pre-battle screen and on the challenge list, so you see a real chance per scouted opponent and
  "Best of N scouted" when they differ.
- **Formation:** each fight is scored 0 to 100 (how much of your army survived a win, or of
  theirs survived a loss). The model estimates what each commander adds in each grid cell,
  allowing for the opponent's power, and tunes its own caution on your fights. If positions stop
  improving predictions, it stops giving formation tips. Roles stay rules: tanks in front,
  back-line commanders behind, at least two in front.

## Pages

Home, Report, History, My commanders and **Data** are in the menu; Auto-log, Teach portraits and
Commanders are under **More**. The Data page shows the database filling up live: every new fight,
commander read and scouted line-up appears within 3 seconds, with ticks for what each fight
holds (troop counts, STATS screen, powers, scouting). It is the quickest way to spot a fight
where you forgot to tap STATS.

## Threat tip

On the pre-battle screen, the enemy commander that has done the most damage to you in earlier
fights (3 or more) is named, and the bar suggests facing it with your tank (a march attacks the
enemy in its own row first).

## Data checks

Each saved fight is checked: impossible troop counts and misread powers are cleared, and fights
where a march is missing (a game notification can cover a name plate) are flagged in History,
where edit lets you add it. Opponents you scouted on the challenge list and then fought get their
levels, expertise and secondaries copied into the fight.

## Experiments after losses

When the formation on screen has lost more than it has won against similar line-ups (two or
more enemy commanders in common), the bar adds one change you have not tried against them yet,
for example "Experiment: 0-2 with this formation vs similar line-ups. Try Joan of Arc in the back
column (swap with Aethelflaed), not tried yet". It starts with the march that did least
damage in those losses and never goes against a commander's role. After a loss the same
suggestion is shown as "Next time: ...". Fights from Sunset and Lost Canyon are pooled.
It only moves marches for now; suggesting different commanders needs My roster filled in.

## Lost Canyon and Prime commanders

- The Lost Canyon challenge list is recognised as well as the Sunset one; fights started from
  it are saved with mode "lost".
- Epic commanders that also exist as a legendary Prime with the same printed name are told
  apart by the portrait frame: the non-purple one is logged as "<name> Prime".

## How recognition works

- Commander names and troop counts are read from the name plates on the pre-battle screen.
- Each time a name is read, the tool saves that commander's portrait. That is how it later
  recognises commanders on the challenge list and stats screen, which show portraits only.
  So an opponent's lineup is recognised on the challenge list only for commanders the tool
  has already met in a fight (or that you named on the Teach page).
- Grid position: column 0 is the column nearest the enemy (stored as "front"), column 1 the
  one behind it ("back"); rows count from the top.

## How the suggestions work

- Starting guess: canyon grade, commander level, tank in front and damage dealers behind,
  and the troop triangle (archers beat infantry, infantry beat cavalry, cavalry beat archers).
- Learning: for every logged fight it tracks how each of your commanders did against each
  enemy commander and in each lane. With few fights the starting guess dominates.

It is a heuristic, not a battle simulator: the game does not publish its formulas.

## If something is read wrongly

On Auto-log, press "Capture now and show what I read" while the screen is up, and send that
text (and a screenshot) so the reader can be tuned. You can also run
`python vision.py some_screenshot.png`.

## Files

- `app.py` web interface            - `watcher.py` background auto-logger
- `vision.py` screen reader         - `portraits.py` portrait library
- `engine.py` recommender           - `db.py` database
- `overlay.py` on-screen status bar
- `priors.py` starting commander data and name list
- `test_vision.py`, `test_e2e.py`, `smoke_test.py` self-checks; `testshots/` sample screens
