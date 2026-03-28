# Claude Usage Bar for Windows

Windows system tray application that monitors your Claude Pro/Team usage in real-time.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![Windows](https://img.shields.io/badge/platform-Windows-0078d4)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **System Tray Icon** — Displays your current usage percentage directly in the taskbar, color-coded by severity (green → yellow → orange → red)
- **Frameless Popup Window** — Clean, modern dark UI appears at the bottom-right corner of the screen
- **Usage Tracking** — Monitors 5-hour and 7-day usage windows, with per-model breakdown (Opus / Sonnet)
- **Extra Usage** — Tracks paid add-on credit consumption
- **Historical Chart** — Visualizes usage trends over 1h / 6h / 1d / 7d / 30d
- **Notifications** — Windows toast alerts when usage crosses configurable thresholds
- **Auto-Polling** — Configurable polling interval (5m / 15m / 30m / 1h)
- **Launch at Login** — Optional Windows startup registration

## Installation

### From Release (recommended)

Download `ClaudeUsageBarModern.exe` from [Releases](https://github.com/character-s/claude-usage-bar-windows/releases) and run it. No installation required.

### From Source

```bash
git clone https://github.com/character-s/claude-usage-bar-windows.git
cd claude-usage-bar-windows

pip install -r requirements.txt
pip install bottle pywebview
# Python 3.13+ requires pre-release pythonnet:
pip install pythonnet --pre

python main_modern.py
```

#### Dependencies

| Package | Purpose |
|---------|---------|
| pystray | System tray icon |
| Pillow | Tray icon rendering |
| requests | Anthropic API calls |
| winotify | Windows toast notifications |
| bottle | Local REST API server |
| pywebview | Frameless webview window |
| pythonnet | WebView2 backend (EdgeChromium) |

## Usage

1. Launch the app — a tray icon appears in the taskbar
2. Click the tray icon to open the popup window
3. Click **Sign in with Claude** and complete the OAuth flow
4. Your usage data will be displayed and auto-refreshed

### Tray Icon

- **Left click** — Toggle popup window
- **Right click** — Context menu (display mode, refresh, quit)
- The icon shows your current usage percentage with color coding

### Settings

Access via the **Settings** link in the popup:

- **Polling Interval** — How often to check usage (5m / 15m / 30m / 1h)
- **Notification Thresholds** — Alert when 5h, 7d, or extra usage exceeds a percentage
- **Launch at Login** — Start automatically with Windows

## Building

```bash
pip install pyinstaller
python -m PyInstaller build_modern.spec --noconfirm
```

Output: `dist/ClaudeUsageBarModern.exe`

## Architecture

```
main_modern.py          Entry point
├── usage_service.py    OAuth + API polling
├── history_service.py  Usage history persistence
├── notification_service.py  Windows toast alerts
├── credentials_store.py     Token storage
├── tray_icon.py        Dynamic tray icon rendering
├── ui_modern.py        Bottle API server + pywebview window
└── web/
    ├── index.html      UI markup
    ├── style.css       Windows 11 dark theme
    ├── app.js          Frontend logic
    └── chart.min.js    Chart.js (bundled)
```

**Threading model:**
- Main thread: pywebview (requires COM initialization)
- Background thread: pystray (system tray)
- Background thread: Bottle REST server
- Background thread: Usage polling

## Data Storage

All data is stored locally at `~/.config/claude-usage-bar/`:

| File | Contents |
|------|----------|
| `credentials.json` | OAuth tokens |
| `history.json` | Usage history (30-day retention) |
| `settings.json` | Polling interval, thresholds, preferences |

## License

MIT
