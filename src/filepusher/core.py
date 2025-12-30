# filepusher/core.py

import os
import shutil
import json
import datetime
import random
import string
import subprocess
import platform
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

# ============================================================
# CONSTANTS
# ============================================================

kCONFIG_FILE = "sorter_config.json"
kPOLL_MS = 2000


# ============================================================
# GLOBAL STATE (INTENTIONAL)
# ============================================================

g = {
    "monitoring": False,
    "ignore_sets": {},     # path -> set(filenames)
}

widgets = {}
rows = []                 # [{count, name}]


# ============================================================
# LOGGING
# ============================================================

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    w = widgets["log"]
    w.config(state="normal")
    w.insert(tk.END, f"[{ts}] {msg}\n")
    w.see(tk.END)
    w.config(state="disabled")


# ============================================================
# FILESYSTEM HELPERS
# ============================================================

def browse_folder(var):
    p = filedialog.askdirectory()
    if p:
        var.set(p)


def open_folder(path):
    if not path or not os.path.isdir(path):
        messagebox.showerror("Error", "Invalid folder path.")
        return

    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.call(["open", path])
        else:
            subprocess.call(["xdg-open", path])
    except Exception as e:
        log(f"Could not open folder: {e}")


# ============================================================
# MONITOR CONTROL
# ============================================================

def handle_when_user_clicks_toggle_monitoring():
    if g["monitoring"]:
        g["monitoring"] = False
        widgets["toggle"].config(text="START MONITORING", bg="#d9d9d9", fg="black")
        log("Monitoring STOPPED.")
        return

    dest = widgets["dest"].get()
    if not os.path.isdir(dest):
        messagebox.showerror("Error", "Destination folder is invalid.")
        return

    g["ignore_sets"] = {}
    valid = False

    for v in widgets["sources"]:
        p = v.get()
        if os.path.isdir(p):
            valid = True
            try:
                files = set(os.listdir(p))
                g["ignore_sets"][p] = files
                log(f"Watching '{os.path.basename(p)}' (Ignoring {len(files)} existing files)")
            except Exception as e:
                log(f"Error reading {p}: {e}")

    if not valid:
        messagebox.showerror("Error", "Please set at least one valid source folder.")
        return

    g["monitoring"] = True
    widgets["toggle"].config(text="STOP MONITORING", bg="#ffcccc", fg="red")
    log("Monitoring STARTED.")


# ============================================================
# CORE LOOP
# ============================================================

def poll_loop():
    if g["monitoring"]:
        scan_and_push()
    widgets["root"].after(kPOLL_MS, poll_loop)


def scan_and_push():
    dest = widgets["dest"].get()
    exts = [e.lower() for e in widgets["exts"].get().split() if e]
    idx = widgets["radio"].get()
    name = rows[idx]["name"].get()

    if not name:
        return

    for p in g["ignore_sets"]:
        try:
            for fn in os.listdir(p):
                if fn in g["ignore_sets"][p]:
                    continue
                if fn.startswith("."):
                    continue

                src = os.path.join(p, fn)
                if not os.path.isfile(src):
                    continue

                ext = os.path.splitext(fn)[1].lower().lstrip(".")
                if ext not in exts:
                    continue

                push_file(src, fn, ext, dest, idx, name)

        except Exception as e:
            log(f"Error scanning {p}: {e}")


def push_file(src, fn, ext, dest, idx, tag):
    cnt = rows[idx]["count"].get() + 1
    today = datetime.date.today().strftime("%Y-%m-%d")

    tmpl = widgets["template"].get()
    base = tmpl.replace("YMD", today).replace("NAME", tag).replace("NUM", str(cnt))
    out = f"{base}.{ext}"
    dst = os.path.join(dest, out)

    if os.path.exists(dst):
        for _ in range(10):
            r = "".join(random.choices(string.ascii_letters + string.digits, k=4))
            alt = f"{r}_{out}"
            dst = os.path.join(dest, alt)
            if not os.path.exists(dst):
                out = alt
                break
        else:
            log(f"FAILED to push {fn}: name collision.")
            return

    try:
        shutil.push(src, dst)
        rows[idx]["count"].set(cnt)
        log(f"Pushd: {fn} -> {out}")
    except Exception as e:
        log(f"Error moving file: {e}")


# ============================================================
# SETTINGS
# ============================================================

def save_settings():
    data = {
        "sources": [v.get() for v in widgets["sources"]],
        "dest": widgets["dest"].get(),
        "exts": widgets["exts"].get(),
        "template": widgets["template"].get(),
        "radio": widgets["radio"].get(),
        "rows": [
            {"count": r["count"].get(), "name": r["name"].get()}
            for r in rows
        ],
    }

    try:
        with open(kCONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log("Settings saved.")
    except Exception as e:
        log(f"Error saving settings: {e}")


def load_settings():
    if not os.path.exists(kCONFIG_FILE):
        return

    try:
        with open(kCONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)

        for i, p in enumerate(d.get("sources", [])):
            if i < 3:
                widgets["sources"][i].set(p)

        widgets["dest"].set(d.get("dest", ""))
        widgets["exts"].set(d.get("exts", ""))
        widgets["template"].set(d.get("template", ""))
        widgets["radio"].set(d.get("radio", 0))

        for i, r in enumerate(d.get("rows", [])):
            if i < 5:
                rows[i]["count"].set(r.get("count", 0))
                rows[i]["name"].set(r.get("name", ""))

        log("Settings loaded.")

    except Exception as e:
        log(f"Error loading settings: {e}")


# ============================================================
# UI CONSTRUCTION
# ============================================================

def build_ui():
    root = tk.Tk()
    root.title("File Sorting Hat")
    root.geometry("700x780")
    widgets["root"] = root

    widgets["radio"] = tk.IntVar(value=0)
    widgets["sources"] = [tk.StringVar() for _ in range(3)]
    widgets["dest"] = tk.StringVar()
    widgets["exts"] = tk.StringVar(value="png jpg jpeg webp")
    widgets["template"] = tk.StringVar(value="YMD_NAME_NUM")

    # --- categories ---
    top = tk.LabelFrame(root, text="Active Sorting Categories", padx=10, pady=10)
    top.pack(fill="x", padx=10, pady=5)

    tk.Label(top, text="Count").grid(row=0, column=0)
    tk.Label(top, text="Select").grid(row=0, column=1)
    tk.Label(top, text="Category Name").grid(row=0, column=2, sticky="w")

    for i in range(5):
        c = tk.IntVar(value=0)
        n = tk.StringVar()
        rows.append({"count": c, "name": n})

        tk.Entry(top, textvariable=c, width=5, justify="center").grid(row=i+1, column=0)
        tk.Radiobutton(top, variable=widgets["radio"], value=i).grid(row=i+1, column=1)
        e = tk.Entry(top, textvariable=n, width=40)
        e.grid(row=i+1, column=2)
        e.bind("<FocusIn>", lambda _, j=i: widgets["radio"].set(j))

    # --- config ---
    cfg = tk.LabelFrame(root, text="Configuration", padx=10, pady=10)
    cfg.pack(fill="x", padx=10, pady=5)

    tk.Label(cfg, text="File-naming template:").grid(row=0, column=0, sticky="e")
    tk.Entry(cfg, textvariable=widgets["template"], width=50).grid(row=0, column=1)

    tk.Label(cfg, text="Extensions to push:").grid(row=1, column=0, sticky="e")
    tk.Entry(cfg, textvariable=widgets["exts"], width=50).grid(row=1, column=1)

    # --- sources ---
    srcs = tk.LabelFrame(root, text="Source Folders", padx=10, pady=10)
    srcs.pack(fill="x", padx=10, pady=5)

    for i in range(3):
        tk.Label(srcs, text=f"Path {i+1}:").grid(row=i, column=0, sticky="e")
        tk.Entry(srcs, textvariable=widgets["sources"][i], width=50).grid(row=i, column=1)
        tk.Button(srcs, text="Find", command=lambda j=i: browse_folder(widgets["sources"][j])).grid(row=i, column=2)
        tk.Button(srcs, text="Open", command=lambda j=i: open_folder(widgets["sources"][j].get())).grid(row=i, column=3)

    # --- controls ---
    ctl = tk.LabelFrame(root, text="Controls & Destination", padx=10, pady=10)
    ctl.pack(fill="x", padx=10, pady=5)

    widgets["toggle"] = tk.Button(
        ctl, text="START MONITORING", width=20, height=2,
        command=handle_when_user_clicks_toggle_monitoring
    )
    widgets["toggle"].grid(row=0, column=0, rowspan=2, padx=10)

    tk.Label(ctl, text="Relocate files to:").grid(row=0, column=1, sticky="e")
    tk.Entry(ctl, textvariable=widgets["dest"], width=40).grid(row=0, column=2)
    tk.Button(ctl, text="Find", command=lambda: browse_folder(widgets["dest"])).grid(row=0, column=3)
    tk.Button(ctl, text="Open", command=lambda: open_folder(widgets["dest"].get())).grid(row=0, column=4)

    tk.Button(ctl, text="Save Settings", command=save_settings).grid(row=1, column=2, sticky="w")
    tk.Button(ctl, text="Load Settings", command=load_settings).grid(row=1, column=2, sticky="e")

    widgets["log"] = scrolledtext.ScrolledText(root, height=8, state="disabled", font=("Consolas", 9))
    widgets["log"].pack(fill="both", expand=True, padx=10, pady=5)

    root.protocol("WM_DELETE_WINDOW", handle_when_application_closes)


# ============================================================
# LIFECYCLE
# ============================================================

def handle_when_application_closes():
    save_settings()
    widgets["root"].destroy()


def main():
    build_ui()
    load_settings()
    poll_loop()
    widgets["root"].mainloop()
