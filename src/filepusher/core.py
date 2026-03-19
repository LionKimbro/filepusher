# filepusher/core.py

from pathlib import Path
import datetime
import json
import random
import string
import platform
import subprocess
import shutil
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

# ============================================================
# CONSTANTS
# ============================================================

CONFIG_FILE = Path("sorter_config.json")
POLL_MS = 2000

TRANSFER_COPY = "copy"
TRANSFER_MOVE = "move"

# ============================================================
# GLOBAL STATE (INTENTIONAL)
# ============================================================

g = {
    "monitoring": False,
    "transfer_mode": TRANSFER_COPY,
    "active_category": 0,
    "fatal_error": False,
    "last_error": "",
    "current_path": None,          # Path | None
    "time_limit_minutes": 15,      # int | None; None means disabled
    "monitor_stop_at": None,       # float epoch seconds | None
}

widgets = {}
rows = []
ignore_sets = {}                  # Path -> set[str]

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
# UI HELPERS
# ============================================================

def browse_folder(var):
    p = filedialog.askdirectory()
    if p:
        var.set(p)

def open_folder(path_text):
    p = Path(path_text) if path_text else None
    if not p or not p.is_dir():
        messagebox.showerror("Error", "Invalid folder path.")
        return
    try:
        if platform.system() == "Windows":
            import os
            os.startfile(str(p))
        elif platform.system() == "Darwin":
            subprocess.call(["open", str(p)])
        else:
            subprocess.call(["xdg-open", str(p)])
    except Exception as e:
        log(f"Could not open folder: {e}")

def ui_set_idle():
    widgets["toggle"].config(text="START MONITORING", bg="#d9d9d9", fg="black")
    widgets["tar"].config(state="normal")
    widgets["doit"].config(state="normal")
    update_countdown_ui()

def ui_set_monitoring():
    widgets["toggle"].config(text="STOP MONITORING", bg="#ffcccc", fg="red")
    widgets["tar"].config(state="disabled")
    widgets["doit"].config(state="disabled")
    update_countdown_ui()

def sync_from_ui():
    g["active_category"] = widgets["radio_category"].get()
    g["transfer_mode"] = widgets["radio_mode"].get()

def format_hhmmss(total_seconds):
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def update_countdown_ui():
    frame = widgets.get("time_limit_countdown_frame")
    if not frame:
        return

    show = (
        g["monitoring"]
        and g["time_limit_minutes"] is not None
        and g["monitor_stop_at"] is not None
    )
    if not show:
        frame.pack_forget()
        return

    remaining = max(0, int(g["monitor_stop_at"] - time.time()))
    widgets["time_limit_countdown_value"].config(text=format_hhmmss(remaining))
    if not frame.winfo_ismapped():
        frame.pack(side="left")

def stop_monitoring(log_message):
    g["monitoring"] = False
    g["monitor_stop_at"] = None
    ui_set_idle()
    log(log_message)

# ============================================================
# FAILURE RULE
# ============================================================

def transfer_failure(reason):
    g["fatal_error"] = True
    g["monitoring"] = False
    g["monitor_stop_at"] = None
    g["last_error"] = reason
    ui_set_idle()
    log(f"FATAL: {reason}")
    messagebox.showerror("File Pusher - Fatal Error", reason)

# ============================================================
# TAR / DO IT
# ============================================================

def do_tar():
    ignore_sets.clear()
    for v in widgets["sources"]:
        p = Path(v.get())
        if p.is_dir():
            ignore_sets[p] = {x.name for x in p.iterdir() if x.is_file()}
            log(f"TAR: '{p.name}' ({len(ignore_sets[p])} files ignored)")

def do_it():
    if g["fatal_error"]:
        return
    scan_and_push()

# ============================================================
# MONITOR CONTROL
# ============================================================

def handle_set_time_limit():
    raw = widgets["time_limit"].get().strip()
    try:
        minutes = int(raw)
    except ValueError:
        messagebox.showerror("Error", "Time limit must be a whole number of minutes.")
        return False

    if minutes < 0:
        messagebox.showerror("Error", "Time limit cannot be negative.")
        return False

    if minutes == 0:
        g["time_limit_minutes"] = None
        g["monitor_stop_at"] = None
        log("Time limit cleared.")
        update_countdown_ui()
        return True

    g["time_limit_minutes"] = minutes
    if g["monitoring"]:
        g["monitor_stop_at"] = time.time() + (minutes * 60)
    log(f"Time limit set to {minutes} minute(s).")
    update_countdown_ui()
    return True

def handle_toggle_monitoring():
    if g["monitoring"]:
        stop_monitoring("Monitoring STOPPED.")
        return

    if not handle_set_time_limit():
        return

    dest = Path(widgets["dest"].get())
    if not dest.is_dir():
        messagebox.showerror("Error", "Destination folder is invalid.")
        return

    sync_from_ui()
    g["fatal_error"] = False
    g["last_error"] = ""

    do_tar()

    g["monitoring"] = True
    if g["time_limit_minutes"] is None:
        g["monitor_stop_at"] = None
    else:
        g["monitor_stop_at"] = time.time() + (g["time_limit_minutes"] * 60)
    ui_set_monitoring()
    log(f"Monitoring STARTED. Mode={g['transfer_mode'].upper()}")

# ============================================================
# CORE LOOP
# ============================================================

def poll_loop():
    if g["monitoring"]:
        do_it()
    widgets["root"].after(POLL_MS, poll_loop)

def countdown_loop():
    if g["monitoring"] and g["time_limit_minutes"] is not None and g["monitor_stop_at"] is not None:
        if time.time() >= g["monitor_stop_at"]:
            stop_monitoring("Monitoring STOPPED (time limit reached).")
        else:
            update_countdown_ui()
    else:
        update_countdown_ui()
    widgets["root"].after(500, countdown_loop)

def scan_and_push():
    sync_from_ui()

    dest = Path(widgets["dest"].get())
    idx = g["active_category"]
    if idx < 0 or idx >= len(rows):
        return

    tag = rows[idx]["name"].get().strip()
    if not tag:
        return

    ext_text = widgets["exts"].get().strip()
    use_all_exts = (ext_text == "*")
    exts = {e.lower().lstrip(".") for e in ext_text.split()} if not use_all_exts else None

    for src_dir in list(ignore_sets.keys()):
        for path in src_dir.iterdir():
            if path.name in ignore_sets[src_dir]:
                continue
            if not path.is_file():
                continue
            if not use_all_exts:
                ext = path.suffix.lower().lstrip(".")
                if ext not in exts:
                    continue

            g["current_path"] = path
            push_current_file(dest, tag)

            if g["fatal_error"]:
                return

# ============================================================
# FILE NAMING
# ============================================================

def make_output_filename(tag):
    path = g["current_path"]
    tmpl = widgets["template"].get().strip()

    if not tmpl:
        return path.name

    cnt = rows[g["active_category"]]["count"].get() + 1
    today = datetime.date.today().strftime("%Y-%m-%d")

    base = (
        tmpl.replace("YMD", today)
            .replace("NAME", tag)
            .replace("NUM", str(cnt))
    )
    return base + path.suffix

def resolve_collision(dest, name):
    candidate = dest / name
    if not candidate.exists():
        return candidate
    for _ in range(10):
        r = "".join(random.choices(string.ascii_letters + string.digits, k=4))
        alt = dest / f"{r}_{name}"
        if not alt.exists():
            return alt
    transfer_failure(f"Name collision: {name}")
    return None

# ============================================================
# TRANSFER PROCEDURE
# ============================================================

def push_current_file(dest, tag):
    src = g["current_path"]
    out_name = make_output_filename(tag)
    dst = resolve_collision(dest, out_name)
    if not dst:
        return

    try:
        shutil.copy2(src, dst)
    except Exception as e:
        transfer_failure(f"Copy failed: {e}")
        return

    try:
        if src.stat().st_size != dst.stat().st_size:
            transfer_failure("Byte-count mismatch after copy.")
            return
    except Exception as e:
        transfer_failure(f"Stat failed: {e}")
        return

    if g["transfer_mode"] == TRANSFER_MOVE:
        try:
            src.unlink()
        except Exception as e:
            transfer_failure(f"Delete failed: {e}")
            return

    rows[g["active_category"]]["count"].set(
        rows[g["active_category"]]["count"].get() + 1
    )
    ignore_sets[src.parent].add(src.name)

    log(f"Pushed: {src.name} → {dst.name}")
    g["current_path"] = None

# ============================================================
# SETTINGS
# ============================================================

def save_settings():
    data = {
        "sources": [v.get() for v in widgets["sources"]],
        "dest": widgets["dest"].get(),
        "exts": widgets["exts"].get(),
        "template": widgets["template"].get(),
        "active_category": widgets["radio_category"].get(),
        "transfer_mode": widgets["radio_mode"].get(),
        "time_limit_minutes": 0 if g["time_limit_minutes"] is None else g["time_limit_minutes"],
        "rows": [{"count": r["count"].get(), "name": r["name"].get()} for r in rows],
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log("Settings saved.")

def load_settings():
    if not CONFIG_FILE.exists():
        return
    d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    for i, p in enumerate(d.get("sources", [])):
        if i < len(widgets["sources"]):
            widgets["sources"][i].set(p)

    widgets["dest"].set(d.get("dest", ""))
    widgets["exts"].set(d.get("exts", ""))
    widgets["template"].set(d.get("template", "YMD_NAME_NUM"))
    widgets["radio_category"].set(d.get("active_category", 0))
    widgets["radio_mode"].set(d.get("transfer_mode", TRANSFER_COPY))

    raw_minutes = d.get("time_limit_minutes", 15)
    try:
        minutes = int(raw_minutes)
    except (ValueError, TypeError):
        minutes = 15
    if minutes < 0:
        minutes = 15
    if minutes == 0:
        g["time_limit_minutes"] = None
        widgets["time_limit"].set("0")
    else:
        g["time_limit_minutes"] = minutes
        widgets["time_limit"].set(str(minutes))

    for i, r in enumerate(d.get("rows", [])):
        if i < len(rows):
            rows[i]["count"].set(r.get("count", 0))
            rows[i]["name"].set(r.get("name", ""))

    log("Settings loaded.")

# ============================================================
# UI
# ============================================================

def build_ui():
    root = tk.Tk()
    root.title("File Pusher")
    root.geometry("700x820")
    widgets["root"] = root

    widgets["radio_category"] = tk.IntVar(value=0)
    widgets["radio_mode"] = tk.StringVar(value=TRANSFER_COPY)

    widgets["sources"] = [tk.StringVar() for _ in range(3)]
    widgets["dest"] = tk.StringVar()
    widgets["exts"] = tk.StringVar(value="png jpg jpeg webp")
    widgets["template"] = tk.StringVar(value="YMD_NAME_NUM")
    widgets["time_limit"] = tk.StringVar(value="15")

    # Categories
    top = tk.LabelFrame(root, text="Active Sorting Categories", padx=10, pady=10)
    top.pack(fill="x", padx=10, pady=5)

    tk.Label(top, text="Count").grid(row=0, column=0)
    tk.Label(top, text="Select").grid(row=0, column=1)
    tk.Label(top, text="Category Name").grid(row=0, column=2)

    for i in range(5):
        c = tk.IntVar(value=0)
        n = tk.StringVar()
        rows.append({"count": c, "name": n})

        tk.Entry(top, textvariable=c, width=5).grid(row=i+1, column=0)
        tk.Radiobutton(top, variable=widgets["radio_category"], value=i).grid(row=i+1, column=1)
        tk.Entry(top, textvariable=n, width=40).grid(row=i+1, column=2)

    # Configuration
    cfg = tk.LabelFrame(root, text="Configuration", padx=10, pady=10)
    cfg.pack(fill="x", padx=10, pady=5)

    tk.Label(cfg, text="File-naming template:").grid(row=0, column=0, sticky="e")
    tk.Entry(cfg, textvariable=widgets["template"], width=50).grid(row=0, column=1)

    tk.Label(cfg, text="Extensions to push:").grid(row=1, column=0, sticky="e")
    tk.Entry(cfg, textvariable=widgets["exts"], width=50).grid(row=1, column=1)

    tk.Label(cfg, text="Transfer mode:").grid(row=2, column=0, sticky="e")
    mode = tk.Frame(cfg)
    mode.grid(row=2, column=1, sticky="w")
    tk.Radiobutton(mode, text="Copy", variable=widgets["radio_mode"], value=TRANSFER_COPY).pack(side="left")
    tk.Radiobutton(mode, text="Move", variable=widgets["radio_mode"], value=TRANSFER_MOVE).pack(side="left")

    # Sources
    srcs = tk.LabelFrame(root, text="Source Folders", padx=10, pady=10)
    srcs.pack(fill="x", padx=10, pady=5)

    for i in range(3):
        tk.Label(srcs, text=f"Path {i+1}:").grid(row=i, column=0, sticky="e")
        tk.Entry(srcs, textvariable=widgets["sources"][i], width=50).grid(row=i, column=1)
        tk.Button(srcs, text="Find", command=lambda j=i: browse_folder(widgets["sources"][j])).grid(row=i, column=2)
        tk.Button(srcs, text="Open", command=lambda j=i: open_folder(widgets["sources"][j].get())).grid(row=i, column=3)

    # Controls
    ctl = tk.LabelFrame(root, text="Controls & Destination", padx=10, pady=10)
    ctl.pack(fill="x", padx=10, pady=5)

    widgets["toggle"] = tk.Button(
        ctl, text="START MONITORING", width=20, height=2,
        command=handle_toggle_monitoring
    )
    widgets["toggle"].grid(row=0, column=0, columnspan=2, rowspan=2, padx=10, sticky="nsew")

    widgets["tar"] = tk.Button(ctl, text="TAR", width=10, command=do_tar)
    widgets["tar"].grid(row=2, column=0, sticky="w", padx=10)

    widgets["doit"] = tk.Button(ctl, text="DO IT", width=10, command=do_it)
    widgets["doit"].grid(row=2, column=1, sticky="e", padx=10)

    tk.Label(ctl, text="Relocate files to:").grid(row=0, column=2, sticky="e")
    tk.Entry(ctl, textvariable=widgets["dest"], width=40).grid(row=0, column=3)
    tk.Button(ctl, text="Find", command=lambda: browse_folder(widgets["dest"])).grid(row=0, column=4)
    tk.Button(ctl, text="Open", command=lambda: open_folder(widgets["dest"].get())).grid(row=0, column=5)

    subframe = tk.Frame(ctl)
    subframe.grid(row=2, column=2, columnspan=4, sticky="we")
    tk.Button(subframe, text="Save Settings", command=save_settings).grid(row=0, column=0, sticky="w")
    tk.Button(subframe, text="Load Settings", command=load_settings).grid(row=0, column=1, sticky="w")

    time_limit_row = tk.Frame(ctl)
    time_limit_row.grid(row=3, column=0, columnspan=6, sticky="w", padx=10, pady=(8, 0))

    tk.Button(time_limit_row, text="set time limit:", command=handle_set_time_limit).pack(side="left")
    tk.Entry(time_limit_row, textvariable=widgets["time_limit"], width=5).pack(side="left")
    tk.Label(time_limit_row, text="minutes").pack(side="left")

    countdown_frame = tk.Frame(time_limit_row)
    countdown_frame.pack(side="left")
    tk.Label(countdown_frame, text="Monitoring will stop forcibly in ").pack(side="left")
    countdown_value = tk.Label(countdown_frame, text="00:00:00", fg="red")
    countdown_value.pack(side="left")
    widgets["time_limit_countdown_frame"] = countdown_frame
    widgets["time_limit_countdown_value"] = countdown_value
    countdown_frame.pack_forget()

    widgets["log"] = scrolledtext.ScrolledText(root, height=10, state="disabled")
    widgets["log"].pack(fill="both", expand=True, padx=10, pady=5)

    widgets["notes"] = tk.Text(root, height=4)
    widgets["notes"].pack(fill="x", padx=10, pady=5)

    root.protocol("WM_DELETE_WINDOW", lambda: (save_settings(), root.destroy()))

# ============================================================
# ENTRY
# ============================================================

def main():
    build_ui()
    load_settings()
    poll_loop()
    countdown_loop()
    widgets["root"].mainloop()
