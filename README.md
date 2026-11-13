<p align="center"><img src="assets/banner.svg" alt="Sunset Canyon Helper" width="100%"></p>

<p align="center">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-PC%20client-e8a93a?style=for-the-badge&logo=windows&logoColor=white">
  <img alt="Python 3.9+" src="https://img.shields.io/badge/Python-3.9%2B-c9672e?style=for-the-badge&logo=python&logoColor=white">
  <img alt="Last update" src="https://img.shields.io/github/last-commit/struklisavodom/Sunset-Solver?style=for-the-badge&color=5a2a3c&label=updated">
</p>

<p align="center"><b>Watches your screen while you play Sunset Canyon (and Lost Canyon), logs every fight by itself,<br>
and tells you on a small bar how likely you are to win and what to change.</b><br>
The more you play, the better its advice gets.</p>

---

## 📦 Get it

Get **Sunset Helper for friends.zip** from the person who shared this with you.

> [!WARNING]
> Don't use GitHub's *Download ZIP*: that copy is missing the shared-data key and the learned
> commander portraits, so it can't share fights or recognise faces.

## 🛠️ Install

1. **Unzip** the zip, for example onto your Desktop.
2. **Python:** install it from [python.org](https://www.python.org/downloads/).
   On the first installer screen, tick **"Add python.exe to PATH"**.
3. **Tesseract** (reads text on screen): install the Windows version from
   [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki). Keep the default folder.
4. **Packages:** open the unzipped **Sunset Helper** folder, click the address bar, type `cmd`,
   press Enter, and paste:

   ```
   pip install pillow numpy scipy mss pytesseract
   ```

5. **Start:** double-click **Start Sunset Helper.bat**. A small bar appears in the bottom-left corner.

> [!TIP]
> Run **Create taskbar shortcut.bat** once for a Desktop icon you can pin to the taskbar.

## ⚔️ Play

Just play. The bar tells you what is happening:

| The bar says | Meaning |
|---|---|
| 🟠 *Reading..., wait* | Hold on a moment |
| 🟢 *...captured. Continue / OK to start* | Safe to click on |
| 🟢 / 🔴 *Scanned 5/5 \| win ~62%* | An opponent you opened: green = good odds, red = bad |
| 🔵 Blue lines | Tips: what to move, what to try next time |
| ⬆️ *Update available* | Double-click the bar, then **Update now** |

> [!TIP]
> **Tap STATS after each fight.** It gives the tool far better data.

- **Scout:** open the arrow next to players on the challenge list or the leaderboard.
- **Double-click** the bar to open the web pages. **Right-click** it to quit. Drag it to move it.

## 🗺️ The web pages

| Page | What it shows |
|---|---|
| **Home** | Your record, and what the tool has learned so far |
| **Report** | Who does your damage, the weak link, what to upgrade, what opponents field |
| **History** | Every fight. Ones marked *check* need a quick look: open **edit** and fix |
| **My commanders** | Your current team, and each commander's level, skills and gear |
| **Shared** | Everyone's fights pooled (anonymous) |
| More → **Teach portraits** | Faces it saw without a name: type the name once |
| More → **Auto-log** | What the tool sees, capture settings, "show the bar in screenshots" |

To keep your commanders up to date, open them in the game now and then (key **P**), plus their
**SKILLS** and the gear **"?"** popup.

## ⬆️ Updates

When the bar says **Update available**, double-click it and press **Update now** on Home.
It installs the new version and restarts. Your fights and settings are kept.

## 🩹 Something wrong?

- **Nothing happens on start:** open a `cmd` window in the folder (step 4) and run `python app.py`.
  Send the error message to whoever shared the app.
- **Something was read wrongly:** More → Auto-log → *Capture now and show what I read*, and send
  that text plus a screenshot.

---

## 🧠 How it works

- **Reading:** names and troop counts come from the pre-battle screen. Result and stars come
  from the VICTORY/DEFEAT screen. Kills and secondaries come from STATS. Each name it reads also
  teaches it that commander's face, which is how it recognises line-ups on screens that only show portraits.
- **Advice only from proof:** the win chance and formation tips come from models tested on your
  own fights. A model is used only if it predicts fights it had not seen better than your plain
  win rate. Both are re-tested after every fight. Positioning rules from the guides (tanks in front,
  at least two marches in front, nukers opposite their tank) apply until your own data says more.
- **Your data stays yours:** everything is stored in this folder (`rok_canyon.db`, `captures/`).
  Shared fights carry a random player id only, never player or opponent names.

## 🔑 For the person who shares it

- **Sharing setup (once):** the **Shared** page lists the steps: a free Supabase project, one SQL
  script, then `shared.json` with the project URL and the **publishable** key (never the secret key).
- **Make the zip for friends:** `python make_friend_copy.py`. It packs the program, the learned
  portraits and `shared.json`, without your database, captures or gear.
- **Release an update:** raise the number in `version.txt`, commit and push to GitHub. Friends
  see *Update available* within the hour.
- **Self-checks:** `python smoke_test.py`, `python test_vision.py`, `python test_e2e.py`
  (all should end with ALL CHECKS PASSED).
