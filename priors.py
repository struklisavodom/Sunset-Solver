"""Starting knowledge, used until your own battle log takes over.

Source: community canyon grades (AllClash ratings as relayed by rokbuilder.com) and
guides saying Richard is the best tank, and Yi Seong-Gye and Imhotep-type skill
commanders suit the back row. This list is PARTIAL on purpose. Edit grades, troop
types and roles on the Commanders page; those edits are stored in the database.
Troop types are left blank where I was not sure; fill them in.
"""

# name: (troop, role, grade)
SEED = {
    "Alp Arslan":          ("", "any",  "S+"),
    "Sun Tzu Prime":       ("", "back", "S+"),
    "Ragnar Lodbrok Prime": ("", "any", "S+"),
    "Shajar al-Durr":      ("", "any",  "S+"),
    "Constantine I":       ("", "any",  "S+"),
    "Imhotep":             ("", "any",  "S"),
    "Joan of Arc":         ("", "any",  "S"),
    "Sun Tzu":             ("", "back", "A+"),
    "Bjorn Ironside":      ("", "any",  "A"),
    "Kusunoki Masashige":  ("", "any",  "A"),
    "Baibars":             ("", "back", "B+"),
    "Richard I":           ("infantry", "tank", "A"),
    "Yi Seong-Gye":        ("archer", "back", "A"),
    "Mehmed II":           ("", "any",  "A"),
}

GRADE_SCORE = {"S+": 10, "S": 9, "A+": 8, "A": 7, "B+": 6, "B": 5, "C": 3, "": 4}

# Commander names used ONLY to fix spelling when the screen reader gets a letter wrong.
# Nothing is added to your commander list until a name is actually seen in a battle.
KNOWN_NAMES = [
    "Sun Tzu", "Cao Cao", "Richard I", "Joan of Arc", "Charles Martel", "Alexander the Great",
    "Julius Caesar", "Hermann", "Boudica", "Lohar", "Bjorn Ironside", "Yi Seong-Gye", "Scipio Africanus",
    "Constantine I", "Minamoto no Yoshitsune", "Lancelot", "Pelagius", "Kusunoki Masashige", "Baibars", "Saladin",
    "Belisarius", "Attila", "Ramesses II", "Genghis Khan", "Osman I", "Tomyris", "Hannibal Barca",
    "Leonidas I", "Nebuchadnezzar II", "Mulan", "Aethelflaed", "Wu Zetian", "Mehmed II",
    "Alp Arslan", "Imhotep", "Ragnar Lodbrok", "Shajar al-Durr", "Guan Yu", "Cleopatra VII",
    "Takeda Shingen", "Zenobia", "William I", "Eleanor of Aquitaine", "Edward of Woodstock",
    "Jan Zizka", "Harald Sigurdsson", "El Cid", "Chandragupta Maurya", "Cyrus the Great",
    "Flavius Aetius", "Tariq ibn Ziyad", "Thutmose III", "Gilgamesh", "Odysseus", "Lapu-Lapu",
    "Sargon the Great", "Gorgo", "Jadwiga", "Seondeok", "Matilda of Flanders", "Sarka", "Centurion",
    "Gaius Marius", "Tomoe Gozen", "Pyrrhus", "Lancelot", "Mulan", "Thutmose III",
]

# Triangle stated by the guides: archers beat infantry, infantry beat cavalry,
# cavalry beat archers.
BEATS = {"archer": "infantry", "infantry": "cavalry", "cavalry": "archer"}


# Troop type and role for commanders that turned up in logged fights. From general game
# knowledge, so check them on the Commanders page; your edits are never overwritten.
SEED.update({
    "Charles Martel":         ("infantry", "tank", ""),
    "Sun Tzu":                ("infantry", "back", "A+"),
    "Bjorn Ironside":         ("infantry", "any", "A"),
    "Cao Cao":                ("cavalry", "any", ""),
    "Minamoto no Yoshitsune": ("cavalry", "any", ""),
    "Baibars":                ("cavalry", "back", "B+"),
    "Pelagius":               ("cavalry", "any", ""),
    "Belisarius":             ("cavalry", "any", ""),
    "Kusunoki Masashige":     ("archer", "back", "A"),
    "Thutmose III":           ("archer", "back", ""),
})

# From the Sunset Canyon guides (AllClash, riseofkingdomsguides, rokbuilder, RoK Handbook):
# tanks and disablers hold the front; area damage and support sit behind them.
SEED.update({
    "Richard I":           ("infantry", "tank", "A"),
    "Charles Martel":      ("infantry", "tank", ""),
    "Scipio Africanus":    ("", "tank", ""),
    "El Cid":              ("", "tank", ""),
    "Yi Seong-Gye":        ("archer", "back", "S"),
    "Mehmed II":           ("", "back", "A"),
    "Joan of Arc":         ("", "tank", "S"),       # with Matilda as secondary she is a front-line tank
    "Aethelflaed":         ("", "back", ""),        # debuffs and supports nearby marches
    "Imhotep":             ("", "back", "S"),
    "Genghis Khan":        ("cavalry", "any", ""),
    "Boudica":             ("", "any", ""),
    "Tomyris":             ("archer", "back", "S"),
    "Alp Arslan":          ("archer", "back", "S+"),
    "Shajar al-Durr":      ("archer", "back", "S+"),
})

# Single-target damage dealers: guides place them facing the enemy's strongest tank.
NUKERS = {"Minamoto no Yoshitsune", "Genghis Khan", "Boudica", "Pelagius"}

# (primary, secondary, why) named in those guides.
PAIRINGS = [
    ("Sun Tzu", "Joan of Arc", "area damage with Joan's buffs"),
    ("Scipio Africanus", "Sun Tzu", "holds the front and adds area damage"),
    ("Richard I", "Charles Martel", "very hard to kill front march"),
    ("Pelagius", "Baibars", "second front march with cavalry area damage"),
    ("Joan of Arc", "Matilda of Flanders", "very hard to kill front march"),
    ("Aethelflaed", "Joan of Arc", "debuffs enemies and supports neighbours"),
    ("Kusunoki Masashige", "Imhotep", "archer damage from the back"),
    ("Minamoto no Yoshitsune", "Genghis Khan", "single-target burst against a tank"),
    ("Genghis Khan", "Minamoto no Yoshitsune", "single-target burst against a tank"),
    ("Eulji Mundeok", "Osman I", "cheap flank march"),
]

# Epic commanders that also exist as a legendary "Prime" with the same printed name. When
# one of these names shows up on a non-purple (non-epic) portrait it is logged as "<name> Prime".
PRIME_BASES = {"Pelagius", "Sun Tzu", "Joan of Arc", "Boudica", "Scipio Africanus", "Belisarius",
               "Baibars", "Hermann", "Bjorn Ironside", "Lohar", "Kusunoki Masashige", "Osman I"}


def seed_commanders(conn):
    for name, (troop, role, grade) in SEED.items():
        conn.execute(
            "INSERT OR IGNORE INTO commanders(name, troop, role, grade) VALUES (?,?,?,?)",
            (name, troop, role, grade),
        )
        # fill blanks only: commanders auto-added from fights start empty
        conn.execute("UPDATE commanders SET troop=? WHERE name=? AND troop='' AND ?<>''", (troop, name, troop))
        conn.execute("UPDATE commanders SET role=? WHERE name=? AND role='any' AND ?<>'any'", (role, name, role))
        conn.execute("UPDATE commanders SET grade=? WHERE name=? AND grade='' AND ?<>''", (grade, name, grade))
    conn.executemany("INSERT OR IGNORE INTO pairings(primary_cmd, secondary_cmd, note) VALUES (?,?,?)", PAIRINGS)
    conn.commit()
