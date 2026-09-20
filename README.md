# 🐻 Bear Audio Limiter
A "True Volume" per-app audio limiter for Windows that prevents sudden loud spikes from ruining your hearing or your speakers.

## 🚀 Overview
Bear Audio Limiter calculates the real output volume by multiplying the **Peak Volume x App Volume x Master Volume**. If any application exceeds a defined threshold, Bear instantly lowers its volume or mutes it, then gradually restores it once the audio is safe.

## ✨ Features
- **Real-time Monitoring**: Tracks the actual output of every running application.
- **Selective App Limiting**: Optionally protect only the apps you select; saved apps remain selected across restarts.
- **Global and Per-App Protection Settings**: New apps inherit the global defaults, while specific apps can save only the local overrides you configure.
- **Live App Discovery**: Open audio apps automatically appear in Settings while the window is open, without flashing the list.
- **App Icons in Settings**: Running audio apps show their executable icons beside their names.
- **Live Settings Preview**: Global settings and per-app overrides apply immediately while the Settings window is open, then write to disk only when you click **Save & Close**.
- **Predictive Protection**: Instantly reacts to audio spikes before they hit your ears.
- **Customizable Thresholds**: Adjust trigger levels, safe return levels, and mute durations.
- **System Tray Integration**: Runs quietly in the background with a monitor window for real-time stats.
- **Smart Recovery**: Gradually fades volume back to original levels to avoid jarring jumps.

## 🛠️ Installation

### Prerequisites
- Windows OS
- Python 3.8+

### Setup
in releases

## ⚙️ Configuration
The app saves your settings in `%APPDATA%/Bear_AudioLimiter/config.json`.
- **Threshold**: The volume level that triggers protection.
- **Safe Level**: The volume level that must be reached before restoring original volume.
- **Mute Duration**: How long to hold the volume low.
- **Only limit selected apps**: Enable this in Settings, then choose from current audio apps. When you first enable it with no saved choices, every visible app starts checked so you only need to uncheck the apps you do not want limited.
- **Global defaults**: Threshold, safe level, drop volume, mute duration, and mute mode are the defaults for every app.
- **Per-app local settings**: In the app list, each app has a larger centered status icon: `🌐` for global defaults or `🔧` for custom per-app overrides. `💤` means the app is remembered in your settings but is not currently open. Click **App Settings** to open that app's separate live settings menu. Enable only the overrides you want to save; everything else keeps using the global defaults.
- **Dark mode**: Enable the persistent dark interface from Settings.

## 📜 License
This project is licensed under the MIT License.
