from pycaw.pycaw import AudioUtilities, IAudioMeterInformation, ISimpleAudioVolume, IAudioEndpointVolume
from comtypes import CLSCTX_ALL
from copy import deepcopy
import pythoncom
import time
import threading
import os
import json
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
try:
    import win32gui
    import win32ui
except Exception:
    win32gui = None
    win32ui = None
import pystray
from pystray import MenuItem as item
import sys

from bear_settings import (
    DEFAULT_CONFIG,
    PROTECTION_SETTING_KEYS,
    app_checkbox_text,
    app_status_icons,
    app_uses_local_settings,
    default_selected_apps,
    effective_app_config,
    get_app_overrides,
    get_theme,
    normalize_config,
    save_app_overrides,
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
def get_running_audio_app_details():
    """Return {exe name: exe path} for Windows audio sessions."""
    pythoncom.CoInitialize()
    try:
        apps = {}
        for session in AudioUtilities.GetAllSessions():
            if not session.Process:
                continue
            name = session.Process.name()
            if name not in apps:
                try:
                    apps[name] = session.Process.exe()
                except Exception:
                    apps[name] = None
        return dict(sorted(apps.items(), key=lambda item: item[0].casefold()))
    except Exception:
        return {}
    finally:
        pythoncom.CoUninitialize()


def get_running_audio_apps():
    """Return the executable names that currently own Windows audio sessions."""
    return list(get_running_audio_app_details())


def load_app_icon(exe_path, size=40):
    """Extract a high-resolution executable icon as a Tk image, with a Bear fallback."""
    fallback = lambda: ImageTk.PhotoImage(load_my_icon().resize((size, size), Image.Resampling.LANCZOS))
    if not exe_path or not win32gui or not win32ui:
        return fallback()
    large_icons = small_icons = []
    try:
        large_icons, small_icons = win32gui.ExtractIconEx(exe_path, 0)
        icons = large_icons or small_icons
        if not icons:
            return fallback()
        hicon = icons[0]
        hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        bitmap_dc = hdc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(hdc, size, size)
        old_bitmap = bitmap_dc.SelectObject(bitmap)
        bitmap_dc.FillSolidRect((0, 0, size, size), 0x000000)
        win32gui.DrawIconEx(bitmap_dc.GetHandleOutput(), 0, 0, hicon, size, size, 0, None, 3)
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer("RGBA", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRA", 0, 1)
        bitmap_dc.SelectObject(old_bitmap)
        return ImageTk.PhotoImage(image)
    except Exception:
        return fallback()
    finally:
        for icon in large_icons + small_icons:
            try:
                win32gui.DestroyIcon(icon)
            except Exception:
                pass


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

                volume_control = session._ctl.QueryInterface(ISimpleAudioVolume)

                # Unchecked apps must stop being detected/defended immediately,
                # even if they were in the middle of a defense cycle.
                if not should_limit_app(name, config):
                    if name in app_states:
                        volume_control.SetMute(0, None)
                        volume_control.SetMasterVolume(app_states[name][0], None)
                        app_states.pop(name, None)
                    continue

                session_config = effective_app_config(name, config)
                meter = session._ctl.QueryInterface(IAudioMeterInformation)

                raw_peak = meter.GetPeakValue()
                app_mixer = volume_control.GetMasterVolume()
                true_actual = raw_peak * app_mixer * global_master

                if name not in app_states:
                    app_states[name] = [app_mixer, 0, False, 0, session_config["THRESHOLD"]]
                elif len(app_states[name]) < 5:
                    app_states[name].append(session_config["THRESHOLD"])

                if not app_states[name][2] and true_actual > session_config["THRESHOLD"]:
                    app_states[name][0] = app_mixer
                    app_states[name][1] = time.time()
                    app_states[name][2] = True
                    app_states[name][4] = session_config["THRESHOLD"]
                    if session_config["USE_MUTE"]:
                        volume_control.SetMute(1, None)
                    else:
                        volume_control.SetMasterVolume(session_config["LOWER_PERCENT"], None)

                if app_states[name][2]:
                    elapsed = time.time() - app_states[name][1]
                    potential_volume = raw_peak * app_states[name][0] * global_master

                    if potential_volume > max_view_level:
                        max_view_level = potential_volume
                        current_loudest = name

                    if session_config["USE_MUTE"]:
                        volume_control.SetMute(1, None)
                    else:
                        volume_control.SetMute(0, None)
                        volume_control.SetMasterVolume(session_config["LOWER_PERCENT"], None)

                    if session_config["THRESHOLD"] > app_states[name][4] and potential_volume <= session_config["THRESHOLD"]:
                        volume_control.SetMute(0, None)
                        start_v = max(volume_control.GetMasterVolume(), 0.001)
                        end_v = app_states[name][0]
                        for step in range(1, 21):
                            ratio = step / 20
                            new_v = start_v * (end_v / start_v) ** ratio
                            volume_control.SetMasterVolume(new_v, None)
                            time.sleep(0.001)
                        app_states[name][2], app_states[name][3] = False, 0
                        app_states[name][4] = session_config["THRESHOLD"]
                        continue

                    if potential_volume > session_config["THRESHOLD"]:
                        is_defending = True
                        app_states[name][1] = time.time()
                        app_states[name][3] = 0
                        app_states[name][4] = session_config["THRESHOLD"]
                        continue

                    is_defending = True

                    if elapsed >= session_config["MUTE_DURATION"]:
                        if potential_volume < session_config["SAFE_LEVEL"]:
                            app_states[name][3] += 1
                            if app_states[name][3] >= 50:
                                volume_control.SetMute(0, None)

                                start_v = max(volume_control.GetMasterVolume(), 0.001)
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


def _create_app_settings_win(app_name, refresh_callback=None):
    """Open the separate local settings menu for one app."""
    app_win = tk.Toplevel(root)
    app_win.title(f"Bear App Settings - {app_name}")
    app_win.geometry("460x520")
    app_win.minsize(420, 480)
    app_win.attributes("-topmost", True)
    app_win.configure(padx=18, pady=14)
    apply_icon(app_win)

    content = tk.Frame(app_win, padx=12, pady=8)
    content.pack(fill="both", expand=True)

    tk.Label(content, text=app_name, font=("Arial", 13, "bold")).pack(anchor="w")
    tk.Label(
        content,
        text="Uses the global settings unless you enable a local override below. Changes apply live; they are written to config.json only from the main Save & Close button.",
        font=("Arial", 8), wraplength=400, justify="left",
    ).pack(anchor="w", pady=(0, 10))

    local_overrides = get_app_overrides(app_name, config)
    override_vars = {}
    value_vars = {}

    def current_overrides():
        overrides = {}
        for key in PROTECTION_SETTING_KEYS:
            if key in override_vars and override_vars[key].get():
                overrides[key] = value_vars[key].get()
        return overrides

    def save_local_live():
        save_app_overrides(app_name, current_overrides(), config)

    def add_local_slider(label_text, key, from_val, to_val, is_percent=True):
        frame = tk.Frame(content)
        frame.pack(fill="x", pady=6)
        override_vars[key] = tk.BooleanVar(value=key in local_overrides)
        start_value = local_overrides.get(key, config[key])
        value_vars[key] = tk.DoubleVar(value=start_value)
        suffix = "%" if is_percent else "s"

        header = tk.Frame(frame)
        header.pack(fill="x")
        tk.Checkbutton(header, text="Override", variable=override_vars[key], command=save_local_live, font=("Arial", 8, "bold")).pack(side="left")
        shown_value = int(start_value * 100) if is_percent else round(start_value, 1)
        global_value = int(config[key] * 100) if is_percent else round(config[key], 1)
        label = tk.Label(
            header,
            text=f"{label_text}: {shown_value}{suffix}  (global {global_value}{suffix})",
            font=("Arial", 9, "bold"),
        )
        label.pack(side="left", padx=(6, 0))

        def update_label(value):
            override_vars[key].set(True)
            parsed_value = max(from_val, min(to_val, float(value)))
            value_vars[key].set(parsed_value)
            shown = int(parsed_value * 100) if is_percent else round(parsed_value, 1)
            label.config(text=f"{label_text}: {shown}{suffix}  (global {global_value}{suffix})")
            save_local_live()

        ttk.Scale(
            frame, from_=from_val, to=to_val, variable=value_vars[key],
            orient="horizontal", command=update_label, style="Bear.Horizontal.TScale",
        ).pack(fill="x")

    add_local_slider("Trigger Threshold", "THRESHOLD", 0.01, 1.0)
    add_local_slider("Safe Level", "SAFE_LEVEL", 0.01, 1.0)
    add_local_slider("Drop Volume To", "LOWER_PERCENT", 0.0, 0.5)
    add_local_slider("Mute Duration", "MUTE_DURATION", 0.1, 5.0, is_percent=False)

    mute_frame = tk.Frame(content)
    mute_frame.pack(fill="x", pady=(8, 4))
    override_vars["USE_MUTE"] = tk.BooleanVar(value="USE_MUTE" in local_overrides)
    value_vars["USE_MUTE"] = tk.BooleanVar(value=local_overrides.get("USE_MUTE", config["USE_MUTE"]))
    tk.Checkbutton(mute_frame, text="Override", variable=override_vars["USE_MUTE"], command=save_local_live, font=("Arial", 8, "bold")).pack(side="left")

    def mark_mute_override():
        override_vars["USE_MUTE"].set(True)
        save_local_live()

    tk.Checkbutton(
        mute_frame,
        text=f"Mute completely on spike (global {'on' if config['USE_MUTE'] else 'off'})",
        variable=value_vars["USE_MUTE"], command=mark_mute_override, font=("Arial", 9, "bold"),
    ).pack(side="left", padx=(6, 0))

    def clear_local():
        save_app_overrides(app_name, {}, config)
        if refresh_callback:
            refresh_callback()
        app_win.destroy()

    def apply_local():
        save_local_live()
        if refresh_callback:
            refresh_callback()
        app_win.destroy()

    button_row = tk.Frame(content)
    button_row.pack(fill="x", side="bottom", pady=(12, 0))
    tk.Button(button_row, text="Use Global Defaults", command=clear_local, font=("Arial", 9, "bold"), pady=8).pack(side="left", fill="x", expand=True, padx=(0, 5))
    tk.Button(button_row, text="Close", command=apply_local, font=("Arial", 9, "bold"), pady=8).pack(side="left", fill="x", expand=True, padx=(5, 0))

    apply_theme(app_win)


def _create_settings_win():
    settings_win = tk.Toplevel(root)
    settings_win.title("Bear Settings")
    settings_win.geometry("540x740")
    settings_win.minsize(500, 680)
    settings_win.attributes("-topmost", True)
    settings_win.configure(padx=20, pady=16)
    apply_icon(settings_win)
    original_config = deepcopy(config)
    saved_settings = False

    content = tk.Frame(settings_win, padx=12, pady=8)
    content.pack(fill="both", expand=True)

    tk.Label(content, text="Global audio protection defaults", font=("Arial", 13, "bold")).pack(anchor="w", pady=(0, 4))

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

    def toggle_mute():
        config["USE_MUTE"] = mute_var.get()

    tk.Checkbutton(
        content, text="Mute completely on spike", variable=mute_var, command=toggle_mute, font=("Arial", 9),
    ).pack(anchor="w", pady=(6, 8))

    tk.Label(content, text="App selection", font=("Arial", 13, "bold")).pack(anchor="w", pady=(4, 2))
    only_selected_var = tk.BooleanVar(value=config["LIMIT_ONLY_SELECTED"])

    tk.Label(
        content,
        text="Open an app that plays audio and it will appear here. Each app starts with the global defaults. Use App Settings to save only local overrides for that app.",
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
    app_rows = {}
    app_icons = {}
    def mark_live():
        """Settings are applied in memory immediately; disk save waits for Save & Close."""
        return None

    def selected_app_names():
        return [name for name in shown_apps if app_vars.get(name) and app_vars[name].get()]

    def save_selection_live():
        config["LIMIT_ONLY_SELECTED"] = only_selected_var.get()
        config["SELECTED_APPS"] = selected_app_names()
        mark_live()

    def update_app_row(app_name):
        row = app_rows.get(app_name)
        if not row:
            return
        selected = app_vars[app_name].get()
        has_local_settings = app_uses_local_settings(app_name, config)
        theme = get_theme(dark_var.get())
        row_bg = theme["select_bg"] if selected else theme["surface"]
        row["frame"].configure(bg=row_bg)
        row["icon"].configure(bg=row_bg)
        row["status"].configure(bg=row_bg, text=app_status_icons(row["is_running"], has_local_settings))
        row["button"].configure(
            text=app_checkbox_text(
                app_name,
                selected,
                row["is_running"],
                has_local_settings,
            ),
            bg=row_bg,
            activebackground=row_bg,
        )

    def on_app_toggled(app_name):
        update_app_row(app_name)
        save_selection_live()

    def populate_apps(force=False):
        nonlocal shown_apps, app_vars
        selected_folded = {name.casefold() for name, variable in app_vars.items() if variable.get()}
        running_details = get_running_audio_app_details()
        new_shown_apps = sorted(
            set(running_details) | set(config.get("SELECTED_APPS", [])) | set(config.get("APP_SETTINGS", {}).keys()),
            key=str.casefold,
        )
        if not app_vars:
            initial_selected = default_selected_apps(new_shown_apps, config) if only_selected_var.get() else config.get("SELECTED_APPS", [])
            selected_folded = {name.casefold() for name in initial_selected}

        old_state = [
            (name, app_rows[name]["is_running"], app_uses_local_settings(name, config))
            for name in shown_apps
            if name in app_rows
        ]
        new_running_folded = {name.casefold() for name in running_details}
        new_state = [
            (name, name.casefold() in new_running_folded, app_uses_local_settings(name, config))
            for name in new_shown_apps
        ]
        if not force and new_shown_apps == shown_apps and old_state == new_state:
            for name in shown_apps:
                update_app_row(name)
            return

        for child in checklist_frame.winfo_children():
            child.destroy()
        shown_apps = new_shown_apps
        app_vars = {}
        app_rows.clear()
        app_icons.clear()

        for app_name in shown_apps:
            is_running = app_name.casefold() in new_running_folded
            variable = tk.BooleanVar(value=app_name.casefold() in selected_folded)
            app_vars[app_name] = variable

            row_frame = tk.Frame(checklist_frame)
            row_frame.pack(fill="x", anchor="w", pady=1)

            icon = load_app_icon(running_details.get(app_name))
            app_icons[app_name] = icon
            icon_label = tk.Label(row_frame, image=icon, width=48)
            icon_label.pack(side="left", padx=(2, 8))

            row = tk.Checkbutton(
                row_frame, variable=variable, indicatoron=False, anchor="w",
                padx=8, pady=4, relief="flat", bd=0, font=("Arial", 9),
                command=lambda name=app_name: on_app_toggled(name),
            )
            row.pack(side="left", fill="x", expand=True, anchor="w")
            status_label = tk.Label(
                row_frame,
                width=4,
                anchor="center",
                justify="center",
                font=("Segoe UI Emoji", 16, "bold"),
            )
            status_label.pack(side="left", padx=(8, 8))
            tk.Button(
                row_frame,
                text="App Settings",
                command=lambda name=app_name: _create_app_settings_win(name, lambda: populate_apps(force=True)),
                font=("Arial", 8),
                padx=6,
                pady=3,
            ).pack(side="right", padx=(5, 0))
            app_rows[app_name] = {
                "frame": row_frame,
                "icon": icon_label,
                "button": row,
                "status": status_label,
                "is_running": is_running,
            }
            update_app_row(app_name)

        apply_theme(settings_win, dark_var.get())
        for name in shown_apps:
            update_app_row(name)

    def auto_refresh_apps():
        if settings_win.winfo_exists():
            populate_apps()
            settings_win.after(2000, auto_refresh_apps)

    def toggle_only_selected():
        config["LIMIT_ONLY_SELECTED"] = only_selected_var.get()
        if only_selected_var.get() and not config.get("SELECTED_APPS"):
            for variable in app_vars.values():
                variable.set(True)
        save_selection_live()
        for name in shown_apps:
            update_app_row(name)

    def preview_theme():
        config["DARK_MODE"] = dark_var.get()
        apply_theme(settings_win, dark_var.get())
        for name in shown_apps:
            update_app_row(name)
        mark_live()

    only_selected_check = tk.Checkbutton(
        content,
        text="Only limit the apps selected below",
        variable=only_selected_var,
        command=toggle_only_selected,
        font=("Arial", 9, "bold"),
    )
    only_selected_check.pack(anchor="w")

    populate_apps(force=True)
    tk.Button(content, text="Refresh open apps", command=lambda: populate_apps(force=True)).pack(fill="x", pady=(5, 8))

    tk.Checkbutton(
        content, text="Dark mode", variable=dark_var, command=preview_theme,
        font=("Arial", 9, "bold"),
    ).pack(anchor="w", pady=(0, 5))

    def save_and_close_settings():
        nonlocal saved_settings
        save_selection_live()
        saved_settings = True
        save_config(config)
        settings_win.destroy()

    def discard_and_close_settings():
        if not saved_settings:
            config.clear()
            config.update(deepcopy(original_config))
        settings_win.destroy()

    tk.Button(
        content, text="Save & Close", command=save_and_close_settings, font=("Arial", 10, "bold"), pady=9,
    ).pack(fill="x")

    settings_win.protocol("WM_DELETE_WINDOW", discard_and_close_settings)

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
