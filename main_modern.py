"""Claude Usage Bar - Modern UI (Bottle + pywebview) entry point."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pystray

from usage_service import UsageService
from history_service import HistoryService
from notification_service import NotificationService
from codex_service import CodexService
from tray_icon import render_icon, render_unauthenticated_icon
from ui_modern import Api

SETTINGS_FILE = Path.home() / ".config" / "claude-usage-bar" / "settings.json"


class ClaudeUsageBarModernApp:
    def __init__(self):
        self.service = UsageService()
        self.history_service = HistoryService()
        self.notification_service = NotificationService()
        self.codex_service = CodexService()

        self.tray_display_mode = self._load_tray_mode()
        self._widget_mode = self._load_widget_mode()

        self.api = Api(self.service, self.history_service, self.notification_service, self.codex_service)
        self.api.set_quit_callback(self._on_quit)
        self.api.set_exit_widget_callback(self._on_exit_widget)

        self.tray_icon: pystray.Icon | None = None
        self._running = True

    def run(self, silent: bool = False):
        self.history_service.load_history()

        if self.service.is_authenticated:
            self.service.start_polling()

        if self.codex_service.is_authenticated:
            self.codex_service.start_polling()

        self.service.on_update = self._on_usage_update
        self.codex_service.on_update = self._on_codex_update

        # Apply saved widget mode (but not if silent)
        if self._widget_mode and not silent:
            self.api._widget_mode = True

        # Start Bottle server
        self.api.start_server()
        time.sleep(0.5)

        # Start tray icon in BACKGROUND thread (pystray works fine off-main on Windows)
        threading.Thread(target=self._run_tray, daemon=True).start()

        # Run pywebview on MAIN thread (blocks until shutdown)
        self.api.run_webview_main(hidden=silent)

        # Cleanup
        self.history_service.flush_to_disk()
        self.service.stop_polling()
        self.codex_service.stop_polling()

    def _run_tray(self):
        icon_image = self._current_icon()

        menu = pystray.Menu(
            pystray.MenuItem("開く", self._on_tray_click, default=True),
            pystray.MenuItem(
                "ウィジェットモード",
                self._on_toggle_widget,
                checked=lambda item: self._widget_mode,
            ),
            pystray.MenuItem(
                "トレイ表示",
                pystray.Menu(
                    pystray.MenuItem(
                        "5時間",
                        self._set_tray_5h,
                        checked=lambda item: self.tray_display_mode == "5h",
                    ),
                    pystray.MenuItem(
                        "7日間",
                        self._set_tray_7d,
                        checked=lambda item: self.tray_display_mode == "7d",
                    ),
                ),
            ),
            pystray.MenuItem("更新", self._on_refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("終了", self._on_quit),
        )

        self.tray_icon = pystray.Icon(
            "claude-usage-bar",
            icon_image,
            "Claude Usage Bar",
            menu,
        )

        icon_thread = threading.Thread(target=self._periodic_icon_update, daemon=True)
        icon_thread.start()

        self.tray_icon.run()

    def _current_icon(self):
        primary = self.api._load_primary_provider()
        if primary == 'codex' and self.codex_service.is_authenticated:
            return render_icon(
                self.codex_service.pct_primary, self.codex_service.pct_secondary,
                show_mode=self.tray_display_mode,
            )
        if self.service.is_authenticated:
            return render_icon(
                self.service.pct_5h, self.service.pct_7d,
                show_mode=self.tray_display_mode,
            )
        if self.codex_service.is_authenticated:
            return render_icon(
                self.codex_service.pct_primary, self.codex_service.pct_secondary,
                show_mode=self.tray_display_mode,
            )
        return render_unauthenticated_icon()

    def _on_usage_update(self):
        if self.service.usage:
            self.history_service.record_data_point(
                self.service.pct_5h, self.service.pct_7d,
                self.codex_service.pct_primary, self.codex_service.pct_secondary,
            )
            self.notification_service.check_and_notify(
                self.service.pct_5h, self.service.pct_7d, self.service.pct_extra
            )
        self._update_icon()

    def _on_codex_update(self):
        if self.codex_service.usage:
            self.history_service.record_data_point(
                self.service.pct_5h, self.service.pct_7d,
                self.codex_service.pct_primary, self.codex_service.pct_secondary,
            )
        self._update_icon()

    def _update_icon(self):
        if self.tray_icon:
            try:
                self.tray_icon.icon = self._current_icon()
            except Exception:
                pass

    def _periodic_icon_update(self):
        while self._running:
            time.sleep(30)
            self._update_icon()

    def _on_tray_click(self, icon=None, item=None):
        if self._widget_mode:
            self.api.show_browser()
        else:
            self.api.toggle_browser()

    def _on_refresh(self, icon=None, item=None):
        threading.Thread(target=self.service.fetch_usage, daemon=True).start()

    def _on_quit(self, icon=None, item=None):
        self._running = False
        self.history_service.flush_to_disk()
        self.service.stop_polling()
        self.codex_service.stop_polling()
        self.api.shutdown_browser()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

    def _on_exit_widget(self):
        """Called when close button is pressed in widget mode."""
        self._widget_mode = False
        self._save_widget_mode(False)
        self.api._widget_mode = False
        self.api._set_topmost(False)
        # Update tray menu checked state
        if self.tray_icon:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass

    def _on_toggle_widget(self, icon=None, item=None):
        self._widget_mode = not self._widget_mode
        self._save_widget_mode(self._widget_mode)
        if self._widget_mode:
            self.api.enter_widget_mode()
        else:
            self.api.exit_widget_mode()

    def _set_tray_5h(self, icon=None, item=None):
        self.tray_display_mode = "5h"
        self._save_tray_mode("5h")
        self._update_icon()

    def _set_tray_7d(self, icon=None, item=None):
        self.tray_display_mode = "7d"
        self._save_tray_mode("7d")
        self._update_icon()

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
    def _load_widget_mode() -> bool:
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                return bool(data.get("widget_mode", False))
            except Exception:
                pass
        return False

    @staticmethod
    def _save_widget_mode(enabled: bool):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        settings = {}
        if SETTINGS_FILE.exists():
            try:
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        settings["widget_mode"] = enabled
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")

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
    silent = '--silent' in sys.argv
    app = ClaudeUsageBarModernApp()
    app.run(silent=silent)


if __name__ == "__main__":
    main()
