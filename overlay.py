"""Small always-on-top status bar: tells you when a screen has been read and it is safe to
click on, and shows the rough win chance. Standard library only (tkinter).

It sits in the bottom-left corner, where the game shows nothing the reader needs. It cannot
draw over a game in exclusive full screen: use windowed or borderless mode. Drag it to move,
double-click it to open the web pages, right-click it to quit the app."""
import base64
import time
import tkinter as tk
import webbrowser

import updater

COLOURS = {"red": "#ff7b7b", "green": "#5fd38d", "orange": "#ffb347", "white": "#e6e6e6", "grey": "#8a94a3"}


TIP = "#7cc7ff"      # suggestions: a colour no status uses, so advice stands out from "OK to start"
BG = "#14171c"


def run(watcher):
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.9)
    root.configure(bg=BG, highlightthickness=3)
    status = tk.Label(root, font=("Segoe UI", 13, "bold"), bg=BG, padx=12, pady=6, anchor="w", justify="left", wraplength=760)
    status.pack(fill="x")
    strip = tk.Label(root, bg=BG, padx=12)            # the scanned line-up, cut from the screen (challenge list)
    tips = tk.Label(root, font=("Segoe UI", 12), bg=BG, fg=TIP, padx=12, anchor="w", justify="left", wraplength=760)
    shown, flash = {"png": None, "img": None}, {"seq": watcher.scan_seq, "until": 0.0}

    def show_strip(png):
        if png is shown["png"]:
            return
        shown["png"] = png
        try:
            shown["img"] = tk.PhotoImage(data=base64.b64encode(png).decode()) if png else None
        except tk.TclError:
            shown["img"] = None
        if shown["img"]:
            strip.config(image=shown["img"])
            strip.pack(fill="x", pady=(0, 8), after=status)
        else:
            strip.pack_forget()
    root.geometry(f"+8+{root.winfo_screenheight() - 190}")
    moved = []

    def drag(e):
        moved.append(1)
        root.geometry(f"+{e.x_root - 20}+{e.y_root - 12}")
    for w in (status, tips, strip):
        w.bind("<B1-Motion>", drag)
        w.bind("<Double-Button-1>", lambda e: webbrowser.open("http://127.0.0.1:8765"))   # open the web pages
        w.bind("<Button-3>", lambda e: root.destroy())                                    # right-click: quit the app
    applied = [None]

    def capture_rule():
        """Windows: hide the bar from screen captures (the watcher's and your screenshots), unless the
        setting "Show the status bar in my screenshots" is on."""
        want = bool(getattr(watcher, "bar_in_shots", False))
        if want == applied[0]:
            return
        applied[0] = want
        try:
            import ctypes
            ctypes.windll.user32.SetWindowDisplayAffinity(ctypes.windll.user32.GetParent(root.winfo_id()), 0 if want else 0x11)
        except Exception:
            pass
    root.update()
    capture_rule()

    def tick():
        text, colour = watcher.hint
        if updater.STATUS["available"]:
            text += "\nUpdate available: double-click this bar, then Update now"
        head, _, rest = text.partition("\n")             # first line: the state; the rest: advice
        c = COLOURS.get(colour, "#e6e6e6")
        status.config(text=head, fg=c)
        show_strip(watcher.bar_strip)
        capture_rule()
        if watcher.scan_seq != flash["seq"]:           # a new opponent was scanned: flash so it is noticed
            flash.update(seq=watcher.scan_seq, until=time.time() + 0.8)
        if rest:
            tips.config(text="\n".join("\u25b8 " + line for line in rest.splitlines()))
            tips.pack(fill="x", pady=(0, 8))
        else:
            tips.pack_forget()
        # the border follows the state: orange = busy, green = done, red = problem, grey = idle
        edge = "#ffffff" if time.time() < flash["until"] else c
        root.configure(highlightbackground=edge, highlightcolor=edge)
        if not moved:      # grow upwards: the bottom edge stays put above the taskbar
            root.update_idletasks()
            root.geometry(f"+8+{root.winfo_screenheight() - root.winfo_height() - 60}")
        root.after(300, tick)
    tick()
    root.mainloop()
