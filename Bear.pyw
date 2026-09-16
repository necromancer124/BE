from pycaw.pycaw import AudioUtilities, IAudioMeterInformation, ISimpleAudioVolume, IAudioEndpointVolume
from comtypes import CLSCTX_ALL
import pythoncom
import time
import threading
import os
import json
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import pystray
from pystray import MenuItem as item
import sys

from bear_settings import (
    DEFAULT_CONFIG,
    app_checkbox_text,
    get_theme,
    normalize_config,
    should_limit_app,
)

# --- APP DATA SETUP ---
APP_FOLDER = os.path.join(os.getenv("APPDATA"), "Bear_AudioLimiter")
CONFIG_FILE = os.path.join(APP_FOLDER, "config.json")


def save_config(config_to_save):
    os.makedirs(APP_FOLDER, exist_ok=True)
    with open(CONFIG_FILE, "w") as config_file:
        json.dump(config_to_save, config_file, indent=4)


def load_config():
    os.makedirs(APP_FOLDER, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        fresh_config = normalize_config(DEFAULT_CONFIG)
        save_config(fresh_config)
        return fresh_config
    try:
        with open(CONFIG_FILE, "r") as config_file:
            saved_config = json.load(config_file)
        migrated_config = normalize_config(saved_config)
        if migrated_config != saved_config:
            save_config(migrated_config)
        return migrated_config
    except (OSError, ValueError, TypeError):
        return normalize_config(DEFAULT_CONFIG)


config = load_config()
running = True
root = None
max_vol_var = None
loudest_app_var = None
status_var = None
tk_icon = None


# --- ICON LOADER ---
def resource_path(relative_path):
    """Get an absolute resource path in development and PyInstaller builds."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def load_my_icon():
    """Load Bear's tray/window icon, with a simple fallback."""
    path = resource_path("icon.png")
    if os.path.exists(path):
        return Image.open(path)
    return Image.new("RGB", (64, 64), color=(255, 140, 0))


# --- APP SELECTION ---
def get_running_audio_apps():
    """Return the executable names that currently own Windows audio sessions."""
    pythoncom.CoInitialize()
    try:
        names = {
            session.Process.name()
            for session in AudioUtilities.GetAllSessions()
            if session.Process
        }
        return sorted(names, key=str.casefold)
    except Exception:
        return []
    finally:
        pythoncom.CoUninitialize()


# --- THE LOGIC (Prediction & Protection) ---
def limiter_logic():
    global config, running
    pythoncom.CoInitialize()

    devices = AudioUtilities.GetDeviceEnumerator()
    endpoint = devices.GetDefaultAudioEndpoint(0, 0)
    master_interface = endpoint.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    master_vol_control = master_interface.QueryInterface(IAudioEndpointVolume)
    app_states = {}

    while running:
        try:
            global_master = master_vol_control.GetMasterVolumeLevelScalar()
            sessions = AudioUtilities.GetAllSessions()

            max_view_level = 0.0
            current_loudest = "None"
            is_defending = False

            for session in sessions:
                if not session.Process:
                    continue
                name = session.Process.name()

                # Unselected apps are ignored. If an app was already being defended
                # when settings changed, let the original recovery logic finish.
                was_defending = name in app_states and app_states[name][2]
                if not should_limit_app(name, config) and not was_defending:
                    continue

                meter = session._ctl.QueryInterface(IAudioMeterInformation)
                volume_control = session._ctl.QueryInterface(ISimpleAudioVolume)

                raw_peak = meter.GetPeakValue()
                app_mixer = volume_control.GetMasterVolume()
                true_actual = raw_peak * app_mixer * global_master

                if name not in app_states:
                    app_states[name] = [app_mixer, 0, False, 0]

                if not app_states[name][2] and true_actual > config["THRESHOLD"]:
                    app_states[name][0] = app_mixer
                    app_states[name][1] = time.time()
                    app_states[name][2] = True
                    if config["USE_MUTE"]:
                        volume_control.SetMute(1, None)
                    else:
                        volume_control.SetMasterVolume(config["LOWER_PERCENT"], None)

                if app_states[name][2]:
                    is_defending = True
                    elapsed = time.time() - app_states[name][1]
                    potential_volume = raw_peak * app_states[name][0] * global_master

                    if potential_volume > max_view_level:
                        max_view_level = potential_volume
                        current_loudest = name

                    if potential_volume > config["THRESHOLD"]:
                        app_states[name][1] = time.time()
                        app_states[name][3] = 0

                    if elapsed >= config["MUTE_DURATION"]:
                        if potential_volume < config["SAFE_LEVEL"]:
                            app_states[name][3] += 1
                            if app_states[name][3] >= 50:
                                if config["USE_MUTE"]:
                                    volume_control.SetMute(0, None)

                                start_v = config["LOWER_PERCENT"] if not config["USE_MUTE"] else 0.001
                                end_v = app_states[name][0]
                                for step in range(1, 41):
                                    ratio = step / 40
                                    new_v = start_v * (end_v / start_v) ** ratio
                                    volume_control.SetMasterVolume(new_v, None)
                                    time.sleep(0.001)
                                app_states[name][2], app_states[name][3] = False, 0
                        else:
                            app_states[name][3] = 0
                elif true_actual > max_view_level:
                    max_view_level = true_actual
                    current_loudest = name

            if max_vol_var:
                max_vol_var.set(int(max_view_level * 100))
            if loudest_app_var:
                loudest_app_var.set(current_loudest)
            if status_var:
                status_var.set("⚠️ DEFENDING" if is_defending else "✅ OK")

        except Exception:
            pass
        time.sleep(0.05)
    pythoncom.CoUninitialize()


# --- UI THEMING ---
def apply_icon(win):
    global tk_icon
    if tk_icon:
        win.iconphoto(False, tk_icon)


def apply_theme(win, dark_mode=None):
    """Apply the selected light/dark palette to a window and its children."""
    theme = get_theme(config["DARK_MODE"] if dark_mode is None else dark_mode)
    win.configure(bg=theme["bg"])

    style = ttk.Style(win)
    style.configure(
        "Bear.Horizontal.TScale",
        background=theme["surface"],
        troughcolor=theme["entry_bg"],
    )
    style.configure(
        "Bear.Horizontal.TProgressbar",
        background=theme["accent"],
        troughcolor=theme["entry_bg"],
    )

    def style_widget(widget):
        if isinstance(widget, (tk.Frame, tk.Toplevel)):
            widget.configure(bg=theme["bg"] if isinstance(widget, tk.Toplevel) else theme["surface"])
        elif isinstance(widget, tk.Label):
            widget.configure(bg=theme["surface"], fg=theme["fg"])
        elif isinstance(widget, tk.Checkbutton):
            widget.configure(
                bg=theme["surface"], fg=theme["fg"], selectcolor=theme["entry_bg"],
                activebackground=theme["surface"], activeforeground=theme["fg"],
            )
        elif isinstance(widget, tk.Button):
            widget.configure(
                bg=theme["accent"], fg="#ffffff", activebackground=theme["accent"],
                activeforeground="#ffffff", relief="flat",
            )
        elif isinstance(widget, tk.Listbox):
            widget.configure(
                bg=theme["entry_bg"], fg=theme["fg"], selectbackground=theme["select_bg"],
                selectforeground=theme["fg"], highlightbackground=theme["muted_fg"],
                highlightcolor=theme["accent"],
            )
        elif isinstance(widget, tk.Canvas):
            widget.configure(
                bg=theme["surface"], highlightbackground=theme["muted_fg"],
                highlightcolor=theme["accent"],
            )
        for child in widget.winfo_children():
            style_widget(child)

    for child in win.winfo_children():
        style_widget(child)


# --- SETTINGS WINDOW ---
def open_settings():
    root.after(0, _create_settings_win)


def _create_settings_win():
    settings_win = tk.Toplevel(root)
    settings_win.title("Bear Settings")
    settings_win.geometry("500x700")
    settings_win.minsize(460, 640)
    settings_win.attributes("-topmost", True)
    settings_win.configure(padx=20, pady=16)
    apply_icon(settings_win)

    content = tk.Frame(settings_win, padx=12, pady=8)
    content.pack(fill="both", expand=True)

    tk.Label(content, text="Audio protection", font=("Arial", 13, "bold")).pack(anchor="w", pady=(0, 4))

    def add_setting(label_text, key, from_val, to_val, is_percent=True):
        frame = tk.Frame(content)
        frame.pack(fill="x", pady=5)
        display_val = int(config[key] * 100) if is_percent else config[key]
        suffix = "%" if is_percent else "s"
        label = tk.Label(frame, text=f"{label_text}: {display_val}{suffix}", font=("Arial", 9, "bold"))
        label.pack(side="top", anchor="w")
        variable = tk.DoubleVar(value=config[key])

        def update_label(value):
            parsed_value = float(value)
            config[key] = parsed_value
            shown_value = int(parsed_value * 100) if is_percent else round(parsed_value, 1)
            label.config(text=f"{label_text}: {shown_value}{suffix}")

        ttk.Scale(
            frame, from_=from_val, to=to_val, variable=variable,
            orient="horizontal", command=update_label, style="Bear.Horizontal.TScale",
        ).pack(fill="x")

    add_setting("Trigger Threshold", "THRESHOLD", 0.01, 1.0)
    add_setting("Safe Level (Return volume below this)", "SAFE_LEVEL", 0.01, 1.0)
    add_setting("Drop Volume To (If not muting)", "LOWER_PERCENT", 0.0, 0.5)
    add_setting("Mute Duration (Seconds)", "MUTE_DURATION", 0.1, 5.0, is_percent=False)

    mute_var = tk.BooleanVar(value=config["USE_MUTE"])
    tk.Checkbutton(
        content, text="Mute completely on spike", variable=mute_var, font=("Arial", 9),
    ).pack(anchor="w", pady=(6, 8))

    tk.Label(content, text="App selection", font=("Arial", 13, "bold")).pack(anchor="w", pady=(4, 2))
    only_selected_var = tk.BooleanVar(value=config["LIMIT_ONLY_SELECTED"])
    tk.Checkbutton(
        content,
        text="Only limit the apps selected below",
        variable=only_selected_var,
        font=("Arial", 9, "bold"),
    ).pack(anchor="w")
    tk.Label(
        content,
        text="Open an app that plays audio and it will appear here. Selections are saved for next time.",
        font=("Arial", 8), wraplength=430, justify="left",
    ).pack(anchor="w", pady=(0, 5))

    dark_var = tk.BooleanVar(value=config["DARK_MODE"])
    list_frame = tk.Frame(content)
    list_frame.pack(fill="both", expand=True)
    app_canvas = tk.Canvas(list_frame, height=155, highlightthickness=1)
    app_scrollbar = tk.Scrollbar(list_frame, command=app_canvas.yview)
    checklist_frame = tk.Frame(app_canvas)
    checklist_window = app_canvas.create_window((0, 0), window=checklist_frame, anchor="nw")
    app_canvas.configure(yscrollcommand=app_scrollbar.set)
    app_canvas.pack(side="left", fill="both", expand=True)
    app_scrollbar.pack(side="right", fill="y")

    checklist_frame.bind(
        "<Configure>", lambda event: app_canvas.configure(scrollregion=app_canvas.bbox("all")),
    )
    app_canvas.bind(
        "<Configure>", lambda event: app_canvas.itemconfigure(checklist_window, width=event.width),
    )

    shown_apps = []
    app_vars = {}

    def populate_apps():
        nonlocal shown_apps, app_vars
        selected_folded = {
            name.casefold() for name, variable in app_vars.items() if variable.get()
        }
        if not app_vars:
            selected_folded.update(name.casefold() for name in config.get("SELECTED_APPS", []))

        running_apps = get_running_audio_apps()
        shown_apps = sorted(
            set(running_apps) | set(config.get("SELECTED_APPS", [])), key=str.casefold,
        )
        running_folded = {name.casefold() for name in running_apps}

        for child in checklist_frame.winfo_children():
            child.destroy()
        app_vars = {}

        for app_name in shown_apps:
            is_running = app_name.casefold() in running_folded
            variable = tk.BooleanVar(value=app_name.casefold() in selected_folded)
            app_vars[app_name] = variable
            row = tk.Checkbutton(
                checklist_frame, variable=variable, indicatoron=False, anchor="w",
                padx=8, pady=4, relief="flat", bd=0, font=("Arial", 9),
            )

            def update_row(button=row, name=app_name, state=variable, running_now=is_running):
                button.configure(text=app_checkbox_text(name, state.get(), running_now))

            row.configure(command=update_row)
            update_row()
            row.pack(fill="x", anchor="w")

        apply_theme(settings_win, dark_var.get())

    def auto_refresh_apps():
        if settings_win.winfo_exists():
            populate_apps()
            settings_win.after(2000, auto_refresh_apps)

    populate_apps()
    tk.Button(content, text="Refresh open apps", command=populate_apps).pack(fill="x", pady=(5, 8))

    def preview_theme():
        apply_theme(settings_win, dark_var.get())

    tk.Checkbutton(
        content, text="Dark mode", variable=dark_var, command=preview_theme,
        font=("Arial", 9, "bold"),
    ).pack(anchor="w", pady=(0, 5))

    def save():
        config["USE_MUTE"] = mute_var.get()
        config["LIMIT_ONLY_SELECTED"] = only_selected_var.get()
        config["SELECTED_APPS"] = [name for name in shown_apps if app_vars[name].get()]
        config["DARK_MODE"] = dark_var.get()
        save_config(config)
        settings_win.destroy()

    tk.Button(
        content, text="Save & Close", command=save, font=("Arial", 10, "bold"), pady=9,
    ).pack(fill="x")

    apply_theme(settings_win, dark_var.get())
    settings_win.after(2000, auto_refresh_apps)


# --- MONITOR WINDOW ---
def show_monitor():
    root.after(0, _create_monitor_win)


def _create_monitor_win():
    global max_vol_var, loudest_app_var, status_var
    monitor_win = tk.Toplevel(root)
    monitor_win.title("Bear Monitor")
    monitor_win.geometry("320x220")
    monitor_win.attributes("-topmost", True)
    monitor_win.configure(padx=15, pady=15)
    apply_icon(monitor_win)

    panel = tk.Frame(monitor_win, padx=10, pady=8)
    panel.pack(fill="both", expand=True)

    status_var = tk.StringVar(value="✅ OK")
    status_label = tk.Label(panel, textvariable=status_var, font=("Arial", 14, "bold"))
    status_label.pack()

    tk.Label(panel, text="Loudest App:", font=("Arial", 9, "italic")).pack(pady=(10, 0))
    loudest_app_var = tk.StringVar(value="None")
    tk.Label(panel, textvariable=loudest_app_var, font=("Arial", 11, "bold")).pack()

    max_vol_var = tk.IntVar(value=0)
    number_label = tk.Label(panel, text="0%", font=("Arial", 22, "bold"))
    number_label.pack(pady=5)

    progress = ttk.Progressbar(
        panel, length=280, variable=max_vol_var, maximum=100,
        style="Bear.Horizontal.TProgressbar",
    )
    progress.pack()

    apply_theme(monitor_win)
    theme = get_theme(config["DARK_MODE"])

    def update_ui():
        if not running or not monitor_win.winfo_exists():
            return
        if max_vol_var and status_var:
            value = max_vol_var.get()
            number_label.config(text=f"{value}%")
            if "DEFENDING" in status_var.get():
                status_label.config(fg="#ef5350")
                number_label.config(fg="#ef5350")
            else:
                status_label.config(fg=theme["accent"])
                number_label.config(fg=theme["fg"])
            monitor_win.after(100, update_ui)

    update_ui()

    def on_close():
        global max_vol_var, loudest_app_var, status_var
        max_vol_var = loudest_app_var = status_var = None
        monitor_win.destroy()

    monitor_win.protocol("WM_DELETE_WINDOW", on_close)


# --- SYSTEM TRAY ---
def setup_tray():
    icon_img = load_my_icon()

    def on_quit(icon, menu_item):
        global running
        running = False
        icon.stop()
        if root:
            root.quit()
        time.sleep(0.2)
        os._exit(0)

    menu = pystray.Menu(
        item("Show Monitor", show_monitor),
        item("Settings", open_settings),
        item("Exit", on_quit),
    )

    icon = pystray.Icon("BearLimiter", icon_img, "Bear Audio Limiter", menu)
    icon.run()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    my_img = load_my_icon()
    tk_icon = ImageTk.PhotoImage(my_img)
    try:
        root.iconphoto(False, tk_icon)
    except Exception:
        pass

    threading.Thread(target=limiter_logic, daemon=True).start()
    threading.Thread(target=setup_tray, daemon=True).start()
    root.mainloop()
