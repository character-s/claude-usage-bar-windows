"""Claude Usage Bar - Windows system tray application.

Monitors Claude API usage and displays it in the Windows system tray.
Port of https://github.com/Blimp-Labs/claude-usage-bar (macOS) to Windows.
"""

from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from pathlib import Path

# Ensure the script directory is on the path
sys.path.insert(0, str(Path(__file__).parent))

import pystray

from usage_service import UsageService
from history_service import HistoryService
from notification_service import NotificationService
from tray_icon import render_icon, render_unauthenticated_icon
from ui_window import MainWindow

SETTINGS_FILE = Path.home() / ".config" / "claude-usage-bar" / "settings.json"


class ClaudeUsageBarApp:
    def __init__(self):
        self.service = UsageService()
        self.history_service = HistoryService()
        self.notification_service = NotificationService()

        # Tray display mode: "5h" or "7d"
        self.tray_display_mode = self._load_tray_mode()

        # Create root window but keep it completely invisible
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.geometry("0x0+0+0")
        self.root.attributes("-alpha", 0)

        self.main_window = MainWindow(
            self.service, self.history_service, self.notification_service
        )
        self.main_window.set_root(self.root)

        self.tray_icon: pystray.Icon | None = None

        # Wire up callbacks
        self.service.on_update = self._on_usage_update

    def run(self):
        # Load history
        self.history_service.load_history()

        # Start polling if authenticated
        if self.service.is_authenticated:
            self.service.start_polling()

        # Create initial tray icon
        icon_image = self._current_icon()

        menu = pystray.Menu(
            pystray.MenuItem("Open", self._on_tray_click, default=True),
            pystray.MenuItem(
                "Widget Mode",
                self._on_toggle_widget,
                checked=lambda item: self.main_window.is_widget_mode,
            ),
            pystray.MenuItem(
                "Tray Display",
                pystray.Menu(
                    pystray.MenuItem(
                        "5-Hour",
                        self._set_tray_5h,
                        checked=lambda item: self.tray_display_mode == "5h",
                    ),
                    pystray.MenuItem(
                        "7-Day",
                        self._set_tray_7d,
                        checked=lambda item: self.tray_display_mode == "7d",
                    ),
                ),
            ),
            pystray.MenuItem("Refresh", self._on_refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )

        self.tray_icon = pystray.Icon(
            "claude-usage-bar",
            icon_image,
            "Claude Usage Bar",
            menu,
        )

        # Run tray icon in a separate thread
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()

        # Start tkinter main loop
        self._periodic_icon_update()
        self.root.mainloop()

        # Cleanup
        self.history_service.flush_to_disk()
        self.service.stop_polling()
        if self.tray_icon:
            self.tray_icon.stop()

    def _current_icon(self):
        if self.service.is_authenticated:
            return render_icon(self.service.pct_5h, self.service.pct_7d,
                               show_mode=self.tray_display_mode)
        return render_unauthenticated_icon()

    def _on_usage_update(self):
        """Called from background thread when usage data changes."""
        if self.service.usage:
            self.history_service.record_data_point(
                self.service.pct_5h, self.service.pct_7d
            )
            self.notification_service.check_and_notify(
                self.service.pct_5h, self.service.pct_7d, self.service.pct_extra
            )
        self._update_icon()
        # Auto-refresh widget if in widget mode
        if self.main_window.is_widget_mode and self.main_window.window:
            self.root.after(0, self.main_window._refresh_window)

    def _update_icon(self):
        if self.tray_icon:
            try:
                self.tray_icon.icon = self._current_icon()
            except Exception:
                pass

    def _periodic_icon_update(self):
        """Periodically refresh the tray icon."""
        self._update_icon()
        self.root.after(30000, self._periodic_icon_update)

    def _on_tray_click(self, icon=None, item=None):
        self.root.after(0, self.main_window.toggle)

    def _on_toggle_widget(self, icon=None, item=None):
        self.root.after(0, self.main_window.toggle_widget_mode)

    def _set_tray_5h(self, icon=None, item=None):
        self.tray_display_mode = "5h"
        self._save_tray_mode("5h")
        self._update_icon()

    def _set_tray_7d(self, icon=None, item=None):
        self.tray_display_mode = "7d"
        self._save_tray_mode("7d")
        self._update_icon()

    def _on_refresh(self, icon=None, item=None):
        threading.Thread(target=self.service.fetch_usage, daemon=True).start()

    def _on_quit(self, icon=None, item=None):
        self.history_service.flush_to_disk()
        self.service.stop_polling()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.quit)

    @staticmethod
    def _load_tray_mode() -> str:
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                mode = data.get("tray_display_mode", "5h")
                if mode in ("5h", "7d"):
                    return mode
            except Exception:
                pass
        return "5h"

    @staticmethod
    def _save_tray_mode(mode: str):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        settings = {}
        if SETTINGS_FILE.exists():
            try:
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        settings["tray_display_mode"] = mode
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def main():
    app = ClaudeUsageBarApp()
    app.run()


if __name__ == "__main__":
    main()
