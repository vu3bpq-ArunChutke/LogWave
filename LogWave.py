#!/usr/bin/env python3
"""
LogWave — Ham Radio QSO Logger software
Requirements: pandas requests
Save as logwave.py and run with Python 3.8+.
Author      : Arun Chutke (VU#BPQ)
Version     : 1.0.0
License     : MIT License
Developed   : 2026
Description : Amateur Radio Logging Software w

GitHub      : https://github.com/vu3bpq-ArunChutke/LogWave
Contact     : vu3bpq@gmail.com

Copyright (c) 2026 Arun Chutke

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files to deal
in the Software without restriction, subject to the conditions stated
in the LICENSE file.

"""

import tkinter as tk
from PIL import Image, ImageTk  # Pillow library for image handling
from tkinter import ttk, messagebox, filedialog
import sqlite3
import datetime
import xml.etree.ElementTree as ET
import sys
import os
import time

# Optional dependency check
missing = []
try:
    import pandas as pd
except Exception:
    missing.append("pandas")
try:
    import requests
except Exception:
    missing.append("requests")
if missing:
    root = tk.Tk(); root.withdraw()
    messagebox.showerror("Missing packages",
        "Install missing packages:\n    pip install " + " ".join(missing))
    sys.exit(1)

# Theme and constants (tweaked for better contrast and larger fonts)
T = {
    "bg_root": "#060d1a", "bg_panel": "#0b1628", "bg_card": "#0f1f38",
    "bg_input": "#071226", "bg_tree": "#060d1a", "bg_tree_alt":"#0b1628",
    "bg_head": "#03101a",
    "amber":"#f0a500","amber_dim":"#b87c00","cyan":"#00d4ff","cyan_dim":"#007fa0",
    "green":"#00e676","red":"#ff5252","purple":"#ce93d8",
    "fg_bright":"#e8f4fd","fg_normal":"#9ab8d4","fg_dim":"#6b8aa0","fg_head":"#00d4ff",
    "border":"#1a3050","border_hi":"#f0a500",
    "font_ui":"Calibri","font_mono":"Consolas",
}

BANDS   = ["160m","80m","60m","40m","30m","20m","17m","15m","12m","10m","6m","4m","2m","70cm"]
MODES   = ["SSB","CW","FM","AM","FT8","FT4","JS8","RTTY","PSK31","Digi","DMR","Other"]
BAND_COLORS = {"160m":"#a0c4ff","80m":"#ffadad","40m":"#f0a500","30m":"#caffbf",
               "20m":"#00e676","17m":"#9bf6ff","15m":"#bdb2ff","12m":"#ffd6a5",
               "10m":"#ff6b6b","6m":"#f472b6","2m":"#67e8f9","70cm":"#c084fc"}
MODE_COLORS = {"SSB":"#f0a500","CW":"#00e676","FT8":"#ff6b6b","FM":"#9ab8d4",
               "AM":"#ffd6a5","RTTY":"#f472b6","FT4":"#ffadad","DMR":"#ffadad"}

DB_FILE = "logwave.db"

# Database setup
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS qso_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    callsign    TEXT,
    band        TEXT,
    mode        TEXT,
    frequency   REAL,
    rst_sent    TEXT,
    rst_recv    TEXT,
    qth         TEXT,
    name        TEXT,
    utc_datetime TEXT
)""")
conn.commit()

def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

# Migrate missing utc_datetime and normalize callsigns to uppercase
cursor.execute("SELECT id, utc_datetime, callsign FROM qso_log")
for rid, ud, cs in cursor.fetchall():
    if not ud or not str(ud).strip():
        cursor.execute("UPDATE qso_log SET utc_datetime=? WHERE id=?", (_now_utc(), rid))
    if cs and cs != cs.upper():
        cursor.execute("UPDATE qso_log SET callsign=? WHERE id=?", (cs.upper(), rid))
conn.commit()

# Remove exact duplicates on startup (keep lowest id for each callsign+utc_datetime)
def remove_exact_duplicates():
    # Delete rows where (callsign, utc_datetime) duplicates exist, keep the smallest id
    cursor.execute("""
        DELETE FROM qso_log
        WHERE id NOT IN (
            SELECT MIN(id) FROM qso_log
            GROUP BY UPPER(callsign), utc_datetime
        )
    """)
    conn.commit()

remove_exact_duplicates()

# Utilities
def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

def fmt_utc(iso):
    if not iso:
        return ""
    try:
        s = str(iso).strip().replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s).astimezone(datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d  %H:%M:%S")
    except Exception:
        return str(iso)

def normalize_utc(val):
    if val is None:
        return None
    try:
        p = pd.to_datetime(val)
        if p.tzinfo is None:
            p = p.tz_localize(datetime.timezone.utc)
        else:
            p = p.astimezone(datetime.timezone.utc)
        return p.isoformat(timespec="seconds")
    except Exception:
        s = str(val).strip()
        return s[:-1] + "+00:00" if s.endswith("Z") else s

# Online lookup (fallback)
HAMQTH_USER = ""
HAMQTH_PASS = ""

def lookup_callsign_online(callsign):
    cs = (callsign or "").strip().upper()
    if not cs:
        return None, None
    if HAMQTH_USER and HAMQTH_PASS:
        try:
            url = (f"https://www.hamqth.com/xml.php"
                   f"?u={HAMQTH_USER}&p={HAMQTH_PASS}&callsign={cs}")
            r = requests.get(url, timeout=6)
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                return root.findtext(".//nick"), root.findtext(".//qth")
        except Exception:
            pass
    try:
        pfx = cs[:2]
        if cs[0] in "KWN" or pfx in {
            "AA","AB","AC","AD","AE","AF","AG","AH","AI","AJ","AK","AL"}:
            r = requests.get(f"https://callook.info/{cs}/json", timeout=6)
            if r.status_code == 200:
                data = r.json()
                addr = data.get("address") or {}
                qth  = addr.get("line1") or addr.get("city") or addr.get("state")
                return data.get("name"), qth
    except Exception:
        pass
    return None, None

# Main application
class LogWave(tk.Tk):
    MY_CALL = "VU3BPQ"
    MY_NAME = "Arun"

    def __init__(self):
        super().__init__()
        self.title("LogWave  ·  Ham Radio QSO Logger")
        self.geometry("1480x860")
        self.minsize(1100, 700)
        self.configure(bg=T["bg_root"])
        self._build_styles()
        self._build_ui()
        self._configure_tags()
        self._tick_clock()
        self.refresh_table()
        self.update_stats()

    def _build_styles(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        f = T["font_ui"]

        # Frames and labels
        s.configure("TFrame", background=T["bg_root"])
        s.configure("Card.TFrame", background=T["bg_card"])
        s.configure("Panel.TFrame", background=T["bg_panel"])

        # Make left-panel labels brighter and larger for readability
        s.configure("LeftLabel.TLabel", background=T["bg_card"], foreground=T["fg_bright"], font=(f, 12))
        s.configure("LeftSect.TLabel", background=T["bg_card"], foreground=T["amber"], font=(f, 11, "bold"))

        s.configure("TLabel", background=T["bg_root"], foreground=T["fg_normal"], font=(f, 11))
        s.configure("Head.TLabel", background=T["bg_head"], foreground=T["cyan"], font=(f, 18, "bold"))
        s.configure("Sub.TLabel", background=T["bg_head"], foreground=T["fg_dim"], font=(f, 9))
        s.configure("Stat.TLabel", background=T["bg_head"], foreground=T["amber"], font=(f, 10, "bold"))
        s.configure("Clock.TLabel", background=T["bg_head"], foreground=T["cyan"], font=(T["font_mono"], 13, "bold"))
        s.configure("Status.TLabel", background=T["bg_head"], foreground=T["fg_dim"], font=(f, 9))

        # Entry style (larger font, dark background)
        s.configure("TEntry",
            fieldbackground=T["bg_input"], foreground=T["fg_bright"],
            insertcolor=T["cyan"], font=(f, 14), relief="flat", borderwidth=0)

        # Combobox style: ensure readonly fieldbackground is the dark input color and larger font
        s.configure("TCombobox",
            fieldbackground=T["bg_input"], background=T["bg_input"], foreground=T["amber"],
            selectbackground=T["bg_input"], selectforeground=T["amber"], font=(f, 14))
        s.map("TCombobox",
            fieldbackground=[("readonly", T["bg_input"])],
            foreground=[("readonly", T["amber"])],
            selectbackground=[("readonly", T["bg_input"])])

        # Buttons
        s.configure("Amber.TButton",
            background=T["amber"], foreground="#060d1a",
            font=(f, 12, "bold"), relief="flat", borderwidth=0, padding=(10,6))
        s.map("Amber.TButton",
            background=[("active", T["amber_dim"]), ("pressed", "#a07000")])

        s.configure("Cyan.TButton",
            background=T["cyan_dim"], foreground=T["fg_bright"],
            font=(f, 12, "bold"), relief="flat", borderwidth=0, padding=(10,6))
        s.map("Cyan.TButton",
            background=[("active", T["cyan"]), ("pressed", "#005570")])

        s.configure("Ghost.TButton",
            background=T["bg_card"], foreground=T["fg_dim"],
            font=(f, 11), relief="flat", borderwidth=0, padding=(8,4))
        s.map("Ghost.TButton",
            background=[("active", T["border"])],
            foreground=[("active", T["fg_bright"])])

        # Treeview
        s.configure("Treeview",
            background=T["bg_tree"], fieldbackground=T["bg_tree"],
            foreground=T["fg_normal"], font=(f, 11), rowheight=28)
        s.configure("Treeview.Heading",
            background=T["bg_head"], foreground=T["cyan"],
            font=(f, 11, "bold"), relief="flat")
        s.map("Treeview",
            background=[("selected", "#1a3a5a")],
            foreground=[("selected", T["fg_bright"])])

        s.configure("TScrollbar",
            background=T["bg_card"], troughcolor=T["bg_root"],
            arrowcolor=T["fg_dim"], relief="flat", borderwidth=0)

        s.configure("TSeparator", background=T["border"])

    def _build_ui(self):
        # header
        hdr = tk.Frame(self, bg=T["bg_head"], height=72)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        logo_area = tk.Frame(hdr, bg=T["bg_head"])
        logo_area.pack(side="left", fill="y", padx=(18, 0))

        try:
            logo_img = Image.open("logwave_logo.png")
            logo_img = logo_img.resize((64, 64), Image.LANCZOS)  # adjust size as needed
            self.logo_photo = ImageTk.PhotoImage(logo_img)
            logo_label = tk.Label(hdr, image=self.logo_photo, bg=T["bg_head"])
            logo_label.pack(side="left", padx=(12, 8), pady=6)
        except Exception as e:
            print("Logo not found or failed to load:", e)

        tk.Label(logo_area, text="◈  LOGWAVE",
                 bg=T["bg_head"], fg=T["cyan"],
                 font=(T["font_ui"], 22, "bold")).pack(side="left", padx=(0,14), pady=14)



        divider = tk.Frame(logo_area, bg=T["border"], width=2)
        divider.pack(side="left", fill="y", pady=12)

        stn = tk.Frame(logo_area, bg=T["bg_head"])
        stn.pack(side="left", padx=14)
        tk.Label(stn, text=self.MY_CALL,
                 bg=T["bg_head"], fg=T["amber"],
                 font=(T["font_ui"], 16, "bold")).pack(anchor="w")
        tk.Label(stn, text=f"{self.MY_NAME}  ·  QSO Logger",
                 bg=T["bg_head"], fg=T["fg_dim"],
                 font=(T["font_ui"], 10)).pack(anchor="w")

        # right: clock + stats
        right_hdr = tk.Frame(hdr, bg=T["bg_head"])
        right_hdr.pack(side="right", fill="y", padx=18)

        self.clock_var = tk.StringVar(value="--:--:-- UTC")
        tk.Label(right_hdr, textvariable=self.clock_var,
                 bg=T["bg_head"], fg=T["cyan"],
                 font=(T["font_mono"], 15, "bold")).pack(anchor="e", pady=(12,0))

        self.date_var = tk.StringVar(value="")
        tk.Label(right_hdr, textvariable=self.date_var,
                 bg=T["bg_head"], fg=T["fg_dim"],
                 font=(T["font_ui"], 9)).pack(anchor="e")

        # stats row in header
        stats_row = tk.Frame(hdr, bg=T["bg_head"])
        stats_row.pack(side="right", fill="y", padx=24)
        self.stat_vars = {}
        for key, label in [("total","TOTAL QSOs"),("unique","UNIQUE CALLS"),("bands","BANDS WORKED")]:
            box = tk.Frame(stats_row, bg=T["bg_head"])
            box.pack(side="left", padx=12, pady=10)
            self.stat_vars[key] = tk.StringVar(value="—")
            tk.Label(box, textvariable=self.stat_vars[key],
                     bg=T["bg_head"], fg=T["amber"],
                     font=(T["font_ui"], 14, "bold")).pack()
            tk.Label(box, text=label,
                     bg=T["bg_head"], fg=T["fg_dim"],
                     font=(T["font_ui"], 8)).pack()

        tk.Frame(self, bg=T["amber"], height=2).pack(fill="x")

        # body
        body = tk.Frame(self, bg=T["bg_root"])
        body.pack(fill="both", expand=True)

        # left panel
        left = tk.Frame(body, bg=T["bg_card"], width=420)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        # thin right border on left panel
        tk.Frame(body, bg=T["border"], width=2).pack(side="left", fill="y")

        canvas = tk.Canvas(left, bg=T["bg_card"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas, bg=T["bg_card"])
        self.scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._build_left(self.scroll_frame)

        # right panel
        right = tk.Frame(body, bg=T["bg_root"])
        right.pack(side="right", fill="both", expand=True)
        self._build_right(right)

        # status bar
        tk.Frame(self, bg=T["border"], height=1).pack(fill="x")
        status_bar = tk.Frame(self, bg=T["bg_head"], height=28)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)

        self.status_var = tk.StringVar(value="Ready  ·  Double-click a row to view / edit / delete")
        tk.Label(status_bar, textvariable=self.status_var,
                 bg=T["bg_head"], fg=T["fg_dim"],
                 font=(T["font_ui"], 9), anchor="w").pack(side="left", padx=12)

        tk.Label(status_bar, text=f"DB: {os.path.abspath(DB_FILE)}",
                 bg=T["bg_head"], fg=T["fg_dim"],
                 font=(T["font_ui"], 9)).pack(side="right", padx=12)

    def _build_left(self, parent):
        P = 16; R = 10; IH = 9; F = T["font_ui"]
        INPUT_FONT = (F, 15)
        INPUT_FONT_BOLD = (F, 16, "bold")
        LABEL_FONT = (F, 12)
        SECT_FONT = (F, 12, "bold")

        def section(frame, text):
            tk.Frame(frame, bg=T["border"], height=1).pack(fill="x", padx=P, pady=(R*2, 0))
            tk.Label(frame, text=f"  {text}",
                     bg=T["bg_card"], fg=T["amber"],
                     font=SECT_FONT,
                     anchor="w").pack(fill="x", padx=P, pady=(6, 6))

        def lbl(frame, text):
            tk.Label(frame, text=text,
                     bg=T["bg_card"], fg=T["fg_bright"],
                     font=LABEL_FONT, anchor="w").pack(fill="x", padx=P, pady=(R//2, 0))

        def entry_widget(frame, textvariable, font=INPUT_FONT, **kw):
            e = ttk.Entry(frame, textvariable=textvariable, style="TEntry", font=font, **kw)
            e.pack(fill="x", padx=P, pady=(0, R), ipady=8)
            return e

        def combo_widget(frame, textvariable, values, fg=None, font=INPUT_FONT):
            cb = ttk.Combobox(frame, textvariable=textvariable, values=values, state="readonly", style="TCombobox", font=font)
            # ensure combobox field background is dark and text is visible
            cb.configure(background=T["bg_input"], foreground=T["amber"])
            cb.pack(fill="x", padx=P, pady=(0, R), ipady=6)
            return cb

        banner = tk.Frame(parent, bg="#071a2a")
        banner.pack(fill="x")
        tk.Label(banner, text=f"  {self.MY_CALL}  ·  NEW QSO ENTRY",
                 bg="#071a2a", fg=T["cyan"],
                 font=(F, 14, "bold"), anchor="w", pady=12).pack(fill="x", padx=P)
        tk.Frame(banner, bg=T["amber"], height=2).pack(fill="x")

        section(parent, "CONTACT")
        lbl(parent, "Call-Sign")
        row_cs = tk.Frame(parent, bg=T["bg_card"])
        row_cs.pack(fill="x", padx=P, pady=(0, R))

        self.callsign_var = tk.StringVar()
        cs_entry = ttk.Entry(row_cs, textvariable=self.callsign_var, style="TEntry", font=INPUT_FONT_BOLD)
        cs_entry.pack(side="left", fill="x", expand=True, ipady=10)
        cs_entry.focus_set()
        # ensure uppercase
        self._trace_id = self.callsign_var.trace_add("write", lambda *a: self.callsign_var.set(self.callsign_var.get().upper()))

        check_btn = tk.Button(row_cs, text="LOOK UP",
                              command=self.on_check_callsign,
                              bg=T["cyan_dim"], fg=T["fg_bright"],
                              font=(F, 11, "bold"), relief="flat",
                              cursor="hand2", padx=10, pady=6)
        check_btn.pack(side="left", padx=(8, 0), fill="y")

        lbl(parent, "Name")
        self.name_var = tk.StringVar()
        entry_widget(parent, self.name_var, font=INPUT_FONT)

        lbl(parent, "QTH")
        self.qth_var = tk.StringVar()
        entry_widget(parent, self.qth_var, font=INPUT_FONT)

        section(parent, "RADIO")
        lbl(parent, "Band")
        self.band_var = tk.StringVar(value="40m")
        combo_widget(parent, self.band_var, BANDS, fg=T["amber"], font=INPUT_FONT)

        lbl(parent, "Mode")
        self.mode_var = tk.StringVar(value="SSB")
        combo_widget(parent, self.mode_var, MODES, fg=T["green"], font=INPUT_FONT)

        lbl(parent, "Frequency  (MHz)")
        self.freq_var = tk.StringVar()
        entry_widget(parent, self.freq_var, font=INPUT_FONT)

        section(parent, "SIGNAL REPORT")
        rst_row = tk.Frame(parent, bg=T["bg_card"])
        rst_row.pack(fill="x", padx=P, pady=(0, R))

        rst_left  = tk.Frame(rst_row, bg=T["bg_card"])
        rst_right = tk.Frame(rst_row, bg=T["bg_card"])
        rst_left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        rst_right.pack(side="left", fill="x", expand=True)

        tk.Label(rst_left,  text="RST Sent+(PWR)", bg=T["bg_card"], fg=T["fg_bright"], font=LABEL_FONT).pack(anchor="w")
        tk.Label(rst_right, text="RST Recv", bg=T["bg_card"], fg=T["fg_bright"], font=LABEL_FONT).pack(anchor="w")
        self.rst_sent_var = tk.StringVar(value="59(50W)")
        self.rst_recv_var = tk.StringVar(value="59")
        ttk.Entry(rst_left,  textvariable=self.rst_sent_var, style="TEntry", font=INPUT_FONT, width=6).pack(fill="x", ipady=6)
        ttk.Entry(rst_right, textvariable=self.rst_recv_var, style="TEntry", font=INPUT_FONT, width=6).pack(fill="x", ipady=6)

        tk.Frame(parent, bg=T["border"], height=1).pack(fill="x", padx=P, pady=(16, 0))

        log_btn = tk.Button(parent, text="▶  LOG QSO",
                            command=self.on_log_qso,
                            bg=T["amber"], fg="#060d1a",
                            font=(F, 14, "bold"), relief="flat",
                            cursor="hand2", pady=10)
        log_btn.pack(fill="x", padx=P, pady=(10, 6))

        clr_btn = tk.Button(parent, text="↺  CLEAR FIELDS",
                            command=self.clear_fields,
                            bg=T["bg_input"], fg=T["fg_bright"],
                            font=(F, 11), relief="flat",
                            cursor="hand2", pady=8)
        clr_btn.pack(fill="x", padx=P, pady=(0, 8))

        section(parent, "SEARCH")
        lbl(parent, "Search Callsign")
        search_row = tk.Frame(parent, bg=T["bg_card"])
        search_row.pack(fill="x", padx=P, pady=(0, R))

        self.search_var = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.search_var, style="TEntry", font=INPUT_FONT).pack(side="left", fill="x", expand=True, ipady=6)
        tk.Button(search_row, text="GO",
                  command=self.on_search,
                  bg=T["cyan_dim"], fg=T["fg_bright"],
                  font=(F, 11, "bold"), relief="flat",
                  cursor="hand2", padx=10).pack(side="left", padx=(8,0), fill="y")

        tk.Button(parent, text="◎  SHOW ALL",
                  command=self.on_show_all,
                  bg=T["bg_input"], fg=T["fg_bright"],
                  font=(F, 11), relief="flat",
                  cursor="hand2", pady=8).pack(fill="x", padx=P, pady=(6, 8))

        section(parent, "DATA")
        io_row = tk.Frame(parent, bg=T["bg_card"])
        io_row.pack(fill="x", padx=P, pady=(6, 18))

        tk.Button(io_row, text="⬇ Import Excel/CSV",
                  command=self.on_import,
                  bg=T["bg_input"], fg=T["fg_bright"],
                  font=(F, 11), relief="flat",
                  cursor="hand2").pack(side="left", fill="x", expand=True, pady=4, padx=(0,8))

        tk.Button(io_row, text="⬆  Export Excel/CSV",
                  command=self.on_export,
                  bg=T["bg_input"], fg=T["fg_bright"],
                  font=(F, 11), relief="flat",
                  cursor="hand2").pack(side="left", fill="x", expand=True, pady=4)

    def _build_right(self, parent):
        F = T["font_ui"]

        toolbar = tk.Frame(parent, bg=T["bg_panel"], height=46)
        toolbar.pack(fill="x", padx=0, pady=0)
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text="  QSO LOG",
                 bg=T["bg_panel"], fg=T["cyan"],
                 font=(F, 12, "bold")).pack(side="left", pady=12, padx=(14,0))

        tk.Label(toolbar, text="  ·  Double-click row to view · edit · delete",
                 bg=T["bg_panel"], fg=T["fg_dim"],
                 font=(F, 9)).pack(side="left", pady=12)

        for txt, col in [("SSB", T["amber"]), ("CW", T["green"]),
                          ("FT8", T["red"]), ("ALL", T["fg_dim"])]:
            tk.Label(toolbar, text=f" {txt} ",
                     bg=T["bg_panel"], fg=col,
                     font=(F, 9, "bold"),
                     relief="flat", bd=0).pack(side="right", padx=4, pady=12)
        tk.Label(toolbar, text="MODE ›",
                 bg=T["bg_panel"], fg=T["fg_dim"],
                 font=(F, 9)).pack(side="right", padx=6, pady=12)

        tk.Frame(parent, bg=T["border"], height=1).pack(fill="x")

        tree_frame = tk.Frame(parent, bg=T["bg_root"])
        tree_frame.pack(fill="both", expand=True, padx=0, pady=0)

        cols = ("SNo","Callsign","Name","QTH","Band","Freq","Mode",
                "RST Sent","RST Recv","UTC (Z)")
        self.tree = ttk.Treeview(tree_frame, columns=cols,
                                  show="headings", selectmode="browse",
                                  style="Treeview")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal",  command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        specs = [
            ("SNo",      60,  "center"),
            ("Callsign", 120, "center"),
            ("Name",     180, "w"),
            ("QTH",      180, "w"),
            ("Band",      80, "center"),
            ("Freq",     100, "center"),
            ("Mode",      90, "center"),
            ("RST Sent",  90, "center"),
            ("RST Recv",  90, "center"),
            ("UTC (Z)",  220, "center"),
        ]
        for col, w, anc in specs:
            self.tree.heading(col, text=col,
                command=lambda c=col: self._sort_by(c, False))
            self.tree.column(col, width=w, anchor=anc, stretch=(col=="Name"))

        # row color tags
        self.tree.tag_configure("even",  background=T["bg_tree"])
        self.tree.tag_configure("odd",   background=T["bg_tree_alt"])
        for band, color in BAND_COLORS.items():
            self.tree.tag_configure(f"b_{band}", foreground=color)
        for mode, color in MODE_COLORS.items():
            self.tree.tag_configure(f"m_{mode}", foreground=color)

        self.tree.bind("<Double-1>", self._on_row_double_click)
        self._sort_col = None
        self._sort_rev = False

    def _configure_tags(self):
        # already configured in _build_right; keep for completeness
        pass

    def _tick_clock(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.clock_var.set(now.strftime("%H:%M:%S UTC"))
        self.date_var.set(now.strftime("%Y-%m-%d"))
        self.after(1000, self._tick_clock)

    # LOOKUP: search local DB for exact callsign and populate Name/QTH fields.
    def on_check_callsign(self):
        cs = (self.callsign_var.get() or "").strip().upper()
        if not cs:
            messagebox.showinfo("Lookup", "Enter a callsign first.")
            return

        try:
            cursor.execute("SELECT name, qth FROM qso_log WHERE UPPER(callsign)=? ORDER BY utc_datetime DESC LIMIT 1", (cs,))
            row = cursor.fetchone()
            if row:
                name, qth = row
                self.name_var.set(name or "")
                self.qth_var.set(qth or "")
                self.status_var.set(f"Local lookup: populated Name/QTH for {cs}")
                return
        except Exception as e:
            self.status_var.set(f"Local lookup error: {e}")

        # fallback to online lookup
        name, qth = lookup_callsign_online(cs)
        if name:
            self.name_var.set(name)
        if qth:
            self.qth_var.set(qth)
        if name or qth:
            self.status_var.set(f"Online lookup: populated Name/QTH for {cs}")
        else:
            self.status_var.set(f"No local or online data found for {cs}")
            messagebox.showinfo("Lookup", f"No data found for {cs}")

    def on_log_qso(self):
        cs = (self.callsign_var.get() or "").strip().upper()
        if not cs:
            messagebox.showwarning("Validation", "Callsign is required.")
            return
        band = self.band_var.get()
        mode = self.mode_var.get()
        try:
            freq = float(self.freq_var.get()) if self.freq_var.get().strip() else None
        except Exception:
            messagebox.showwarning("Validation", "Frequency must be a number (MHz).")
            return
        rst_s = self.rst_sent_var.get().strip()
        rst_r = self.rst_recv_var.get().strip()
        qth = self.qth_var.get().strip()
        name = self.name_var.get().strip()
        utc = now_utc()

        # Prevent inserting exact duplicate (callsign + utc_datetime)
        cursor.execute("SELECT id FROM qso_log WHERE UPPER(callsign)=? AND utc_datetime=?", (cs, utc))
        if cursor.fetchone():
            messagebox.showinfo("Duplicate", "An identical QSO already exists (same callsign and UTC).")
            return

        cursor.execute("""
            INSERT INTO qso_log (callsign, band, mode, frequency, rst_sent, rst_recv, qth, name, utc_datetime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (cs, band, mode, freq, rst_s, rst_r, qth, name, utc))
        conn.commit()
        self.status_var.set(f"Logged QSO with {cs} at {fmt_utc(utc)}")
        self.clear_fields()
        self.refresh_table()
        self.update_stats()

    def clear_fields(self):
        self.callsign_var.set("")
        self.name_var.set("")
        self.qth_var.set("")
        self.freq_var.set("")
        self.rst_sent_var.set("59(50W)")
        self.rst_recv_var.set("59")
        self.band_var.set("40m")
        self.mode_var.set("SSB")
        try:
            self.callsign_var.trace_remove("write", self._trace_id)
        except Exception:
            pass
        self._trace_id = self.callsign_var.trace_add("write", lambda *a: self.callsign_var.set(self.callsign_var.get().upper()))

    # refresh_table: optional filter_callsign (string) or filter_rows (pre-fetched rows)
    def refresh_table(self, filter_callsign=None, filter_rows=None):
        for row in self.tree.get_children():
            self.tree.delete(row)

        if filter_rows is not None:
            rows = filter_rows
        else:
            if filter_callsign:
                cursor.execute("SELECT * FROM qso_log WHERE UPPER(callsign) LIKE ? ORDER BY utc_datetime DESC", (f"%{filter_callsign}%",))
            else:
                cursor.execute("SELECT * FROM qso_log ORDER BY utc_datetime DESC")
            rows = cursor.fetchall()

        for idx, row in enumerate(rows, start=1):
            rid, callsign, band, mode, freq, rst_s, rst_r, qth, name, utc_dt = row
            tags = ["even" if idx % 2 == 0 else "odd"]
            if band: tags.append(f"b_{band}")
            if mode: tags.append(f"m_{mode}")
            self.tree.insert("", "end", iid=str(rid), values=(
                idx, callsign, name or "", qth or "", band or "", freq or "", mode or "", rst_s or "", rst_r or "", fmt_utc(utc_dt)
            ), tags=tags)

    def update_stats(self):
        cursor.execute("SELECT COUNT(*) FROM qso_log"); total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT callsign) FROM qso_log"); unique = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT band) FROM qso_log"); bands = cursor.fetchone()[0]
        self.stat_vars["total"].set(str(total)); self.stat_vars["unique"].set(str(unique)); self.stat_vars["bands"].set(str(bands))

    def on_search(self):
        q = (self.search_var.get() or "").strip().upper()
        if not q:
            messagebox.showinfo("Search", "Enter a callsign or fragment to search.")
            return
        self.refresh_table(filter_callsign=q)
        self.status_var.set(f"Filtered by: {q}")

    def on_show_all(self):
        self.search_var.set("")
        self.refresh_table()
        self.status_var.set("Showing all QSOs")

    def on_import(self):
        path = filedialog.askopenfilename(title="Import Excel/CSV", filetypes=[("Excel files","*.xlsx;*.xls"),("CSV files","*.csv"),("All files","*.*")])
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                df = pd.read_csv(path)
            else:
                df = pd.read_excel(path)
            # Normalize column names to lower-case keys for flexibility
            df_columns = {c.lower(): c for c in df.columns}
            inserted = 0
            skipped = 0
            for _, r in df.iterrows():
                cs = str(r.get(df_columns.get("callsign", "callsign")) or "").strip().upper()
                if not cs:
                    continue
                band = r.get(df_columns.get("band", "band")) or ""
                mode = r.get(df_columns.get("mode", "mode")) or ""
                freq_val = r.get(df_columns.get("frequency", "frequency"))
                freq = float(freq_val) if pd.notna(freq_val) and str(freq_val).strip() != "" else None
                rst_s = r.get(df_columns.get("rst_sent", "rst_sent")) or ""
                rst_r = r.get(df_columns.get("rst_recv", "rst_recv")) or ""
                qth = r.get(df_columns.get("qth", "qth")) or ""
                name = r.get(df_columns.get("name", "name")) or ""
                utc_raw = r.get(df_columns.get("utc_datetime", "utc_datetime")) or r.get(df_columns.get("utc", "utc")) or None
                utc = normalize_utc(utc_raw) if utc_raw is not None else now_utc()

                # Check for exact duplicate (callsign + utc_datetime)
                cursor.execute("SELECT id FROM qso_log WHERE UPPER(callsign)=? AND utc_datetime=?", (cs, utc))
                if cursor.fetchone():
                    skipped += 1
                    continue

                cursor.execute("""
                    INSERT INTO qso_log (callsign, band, mode, frequency, rst_sent, rst_recv, qth, name, utc_datetime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (cs, band, mode, freq, rst_s, rst_r, qth, name, utc))
                inserted += 1

            conn.commit()

            # After import, remove any accidental duplicates (keep lowest id per callsign+utc)
            cursor.execute("""
                DELETE FROM qso_log
                WHERE id NOT IN (
                    SELECT MIN(id) FROM qso_log
                    GROUP BY UPPER(callsign), utc_datetime
                )
            """)
            conn.commit()

            self.refresh_table()
            self.update_stats()
            messagebox.showinfo("Import", f"Import completed. Inserted: {inserted}. Skipped duplicates: {skipped}.")
            self.status_var.set(f"Imported {inserted} rows; skipped {skipped} duplicates.")
        except Exception as e:
            messagebox.showerror("Import Error", str(e))
            self.status_var.set("Import failed.")

    def on_export(self):
        path = filedialog.asksaveasfilename(title="Export Excel/CSV", defaultextension=".xlsx", filetypes=[("Excel files","*.xlsx"),("CSV files","*.csv")])
        if not path:
            return
        try:
            cursor.execute("SELECT callsign, band, mode, frequency, rst_sent, rst_recv, qth, name, utc_datetime FROM qso_log ORDER BY utc_datetime DESC")
            rows = cursor.fetchall()
            df = pd.DataFrame(rows, columns=["callsign","band","mode","frequency","rst_sent","rst_recv","qth","name","utc_datetime"])
            if path.lower().endswith(".csv"):
                df.to_csv(path, index=False)
            else:
                df.to_excel(path, index=False)
            messagebox.showinfo("Export", f"Exported {len(df)} rows to {path}")
            self.status_var.set(f"Exported {len(df)} rows.")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))
            self.status_var.set("Export failed.")

    def _on_row_double_click(self, event):
        item = self.tree.focus()
        if not item:
            return
        rid = item
        cursor.execute("SELECT * FROM qso_log WHERE id=?", (rid,))
        row = cursor.fetchone()
        if not row:
            return
        rid, callsign, band, mode, freq, rst_s, rst_r, qth, name, utc_dt = row
        EditDialog(self, rid, callsign, band, mode, freq, rst_s, rst_r, qth, name, utc_dt, self._on_edit_saved, self._on_delete)

    def _on_edit_saved(self, rid, data):
        cursor.execute("""
            UPDATE qso_log SET callsign=?, band=?, mode=?, frequency=?, rst_sent=?, rst_recv=?, qth=?, name=?, utc_datetime=?
            WHERE id=?
        """, (data["callsign"], data["band"], data["mode"], data["frequency"], data["rst_sent"], data["rst_recv"], data["qth"], data["name"], data["utc_datetime"], rid))
        conn.commit()

        # After edit, remove any duplicates that may have been created by editing to match another row
        cursor.execute("""
            DELETE FROM qso_log
            WHERE id NOT IN (
                SELECT MIN(id) FROM qso_log
                GROUP BY UPPER(callsign), utc_datetime
            )
        """)
        conn.commit()

        self.refresh_table()
        self.update_stats()
        self.status_var.set(f"Updated record {rid}")

    def _on_delete(self, rid):
        if messagebox.askyesno("Delete", "Delete this QSO?"):
            cursor.execute("DELETE FROM qso_log WHERE id=?", (rid,))
            conn.commit()
            self.refresh_table()
            self.update_stats()
            self.status_var.set(f"Deleted record {rid}")

    def _sort_by(self, col, reverse):
        col_map = {
            "SNo": None, "Callsign": "callsign", "Name": "name", "QTH": "qth",
            "Band": "band", "Freq": "frequency", "Mode": "mode",
            "RST Sent": "rst_sent", "RST Recv": "rst_recv", "UTC (Z)": "utc_datetime"
        }
        dbcol = col_map.get(col)
        if dbcol:
            cursor.execute(f"SELECT * FROM qso_log ORDER BY {dbcol} {'DESC' if reverse else 'ASC'}")
            rows = cursor.fetchall()
            for i in self.tree.get_children():
                self.tree.delete(i)
            for idx, row in enumerate(rows, start=1):
                rid, callsign, band, mode, freq, rst_s, rst_r, qth, name, utc_dt = row
                tags = ["even" if idx % 2 == 0 else "odd"]
                if band: tags.append(f"b_{band}")
                if mode: tags.append(f"m_{mode}")
                self.tree.insert("", "end", iid=str(rid), values=(
                    idx, callsign, name or "", qth or "", band or "", freq or "", mode or "", rst_s or "", rst_r or "", fmt_utc(utc_dt)
                ), tags=tags)
            self._sort_rev = not reverse
            self._sort_col = col
        else:
            data = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
            try:
                data.sort(reverse=reverse, key=lambda t: float(t[0]) if t[0].replace('.','',1).isdigit() else t[0])
            except Exception:
                data.sort(reverse=reverse, key=lambda t: t[0])
            for index, (_, k) in enumerate(data):
                self.tree.move(k, '', index)
            self._sort_rev = not reverse
            self._sort_col = col

class EditDialog(tk.Toplevel):
    def __init__(self, parent, rid, callsign, band, mode, freq, rst_s, rst_r, qth, name, utc_dt, save_cb, delete_cb):
        super().__init__(parent)
        self.title(f"Edit QSO {callsign}")
        self.resizable(False, False)
        self.rid = rid
        self.save_cb = save_cb
        self.delete_cb = delete_cb
        F = T["font_ui"]
        frame = tk.Frame(self, bg=T["bg_card"], padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        lbl_font = (F, 10)
        entry_font = (F, 12)

        tk.Label(frame, text="Callsign", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=0, column=0, sticky="w")
        self.callsign_var = tk.StringVar(value=callsign)
        ttk.Entry(frame, textvariable=self.callsign_var, style="TEntry", font=entry_font).grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(frame, text="Name", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=1, column=0, sticky="w")
        self.name_var = tk.StringVar(value=name)
        ttk.Entry(frame, textvariable=self.name_var, style="TEntry", font=entry_font).grid(row=1, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(frame, text="QTH", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=2, column=0, sticky="w")
        self.qth_var = tk.StringVar(value=qth)
        ttk.Entry(frame, textvariable=self.qth_var, style="TEntry", font=entry_font).grid(row=2, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(frame, text="Band", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=3, column=0, sticky="w")
        self.band_var = tk.StringVar(value=band)
        ttk.Combobox(frame, textvariable=self.band_var, values=BANDS, state="readonly", style="TCombobox", font=entry_font).grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(frame, text="Mode", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=4, column=0, sticky="w")
        self.mode_var = tk.StringVar(value=mode)
        ttk.Combobox(frame, textvariable=self.mode_var, values=MODES, state="readonly", style="TCombobox", font=entry_font).grid(row=4, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(frame, text="Freq (MHz)", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=5, column=0, sticky="w")
        self.freq_var = tk.StringVar(value=str(freq) if freq is not None else "")
        ttk.Entry(frame, textvariable=self.freq_var, style="TEntry", font=entry_font).grid(row=5, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(frame, text="RST Sent", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=6, column=0, sticky="w")
        self.rst_sent_var = tk.StringVar(value=rst_s)
        ttk.Entry(frame, textvariable=self.rst_sent_var, style="TEntry", font=entry_font).grid(row=6, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(frame, text="RST Recv", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=7, column=0, sticky="w")
        self.rst_recv_var = tk.StringVar(value=rst_r)
        ttk.Entry(frame, textvariable=self.rst_recv_var, style="TEntry", font=entry_font).grid(row=7, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(frame, text="UTC (ISO)", bg=T["bg_card"], fg=T["fg_bright"], font=lbl_font).grid(row=8, column=0, sticky="w")
        self.utc_var = tk.StringVar(value=utc_dt or now_utc())
        ttk.Entry(frame, textvariable=self.utc_var, style="TEntry", font=entry_font).grid(row=8, column=1, sticky="ew", padx=6, pady=4)

        btn_frame = tk.Frame(frame, bg=T["bg_card"])
        btn_frame.grid(row=9, column=0, columnspan=2, pady=(10,0))

        tk.Button(btn_frame, text="Save", command=self.on_save, bg=T["amber"], fg="#060d1a", font=(F,11,"bold")).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Delete", command=self.on_delete, bg=T["bg_input"], fg=T["fg_bright"], font=(F,11)).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Close", command=self.destroy, bg=T["bg_input"], fg=T["fg_bright"], font=(F,11)).pack(side="left", padx=6)

        frame.columnconfigure(1, weight=1)

    def on_save(self):
        data = {
            "callsign": (self.callsign_var.get() or "").strip().upper(),
            "name": self.name_var.get().strip(),
            "qth": self.qth_var.get().strip(),
            "band": self.band_var.get().strip(),
            "mode": self.mode_var.get().strip(),
            "frequency": float(self.freq_var.get()) if self.freq_var.get().strip() else None,
            "rst_sent": self.rst_sent_var.get().strip(),
            "rst_recv": self.rst_recv_var.get().strip(),
            "utc_datetime": normalize_utc(self.utc_var.get().strip() or now_utc())
        }
        self.save_cb(self.rid, data)
        self.destroy()

    def on_delete(self):
        self.delete_cb(self.rid)
        self.destroy()


def show_splash():
        splash = tk.Toplevel()
        splash.overrideredirect(True)
        splash.configure(bg="#060d1a")  # match app background
        splash.geometry("500x400+500+250")  # center window roughly

        # Load logo
        logo = Image.open("logwave_logo.png")
        logo = logo.resize((260, 260), Image.LANCZOS)
        splash_img = ImageTk.PhotoImage(logo)

        # Display logo
        tk.Label(splash, image=splash_img, bg="#060d1a").pack(pady=40)
        tk.Label(splash, text="LogWave", fg="#00d4ff", bg="#060d1a",
                 font=("Calibri", 26, "bold")).pack()
        tk.Label(splash, text="Radio Logging Made Easy!",
                 fg="#f0a500", bg="#060d1a", font=("Calibri", 14)).pack(pady=10)

        splash.attributes("-alpha", 0.0)  # start transparent
        splash.update()

        # Fade in
        for i in range(0, 11):
            splash.attributes("-alpha", i / 10)
            splash.update()
            time.sleep(0.05)

        # Hold for 2 seconds
        time.sleep(2)

        # Fade out
        for i in range(10, -1, -1):
            splash.attributes("-alpha", i / 10)
            splash.update()
            time.sleep(0.05)

        splash.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()  # hide root while splash shows
    show_splash()
    root.destroy()
    app = LogWave()
    app.mainloop()

        

#if __name__ == "__main__":
 #   app = LogWave()
  #  app.mainloop()
