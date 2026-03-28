"""Modern UI layer using Bottle (local web server) + pywebview (frameless)."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import winreg
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import webview
from bottle import Bottle, static_file, request, response

if TYPE_CHECKING:
    from usage_service import UsageService
    from history_service import HistoryService
    from notification_service import NotificationService


def _web_dir() -> str:
    """Return the path to the web/ directory (works both in dev and PyInstaller)."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'web')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Api:
    """Serves Python data to the web UI via Bottle REST endpoints."""

    def __init__(
        self,
        service: UsageService,
        history_service: HistoryService,
        notification_service: NotificationService,
    ):
        self.service = service
        self.history_service = history_service
        self.notification_service = notification_service
        self._quit_callback: Optional[callable] = None
        self._on_exit_widget_callback: Optional[callable] = None

        self.app = Bottle()
        self._setup_routes()

        self.port = _find_free_port()
        self._webview_window: Optional[webview.Window] = None
        self._webview_visible = True
        self._widget_mode = False

    def set_quit_callback(self, callback):
        self._quit_callback = callback

    def set_exit_widget_callback(self, callback):
        self._on_exit_widget_callback = callback

    def _json_response(self, data):
        response.content_type = 'application/json'
        return json.dumps(data)

    def _setup_routes(self):
        app = self.app

        @app.route('/')
        def index():
            return static_file('index.html', root=_web_dir())

        @app.route('/<filepath:path>')
        def serve_static(filepath):
            return static_file(filepath, root=_web_dir())

        @app.route('/api/usage')
        def get_usage():
            return self._json_response(self._get_usage())

        @app.route('/api/history/<range_label>')
        def get_history(range_label):
            return self._json_response(self._get_history(range_label))

        @app.route('/api/settings')
        def get_settings():
            return self._json_response(self._get_settings())

        @app.post('/api/sign-in')
        def sign_in():
            self.service.start_oauth_flow()
            return self._json_response({'ok': True})

        @app.post('/api/submit-code')
        def submit_code():
            data = request.json or {}
            code = data.get('code', '')
            success = self.service.submit_oauth_code(code)
            return self._json_response({
                'success': success,
                'error': self.service.last_error if not success else None,
            })

        @app.post('/api/sign-out')
        def sign_out():
            self.service.sign_out()
            return self._json_response({'ok': True})

        @app.post('/api/refresh')
        def do_refresh():
            threading.Thread(target=self.service.fetch_usage, daemon=True).start()
            return self._json_response({'ok': True})

        @app.post('/api/quit')
        def quit_app():
            if self._quit_callback:
                threading.Thread(target=self._quit_callback, daemon=True).start()
            return self._json_response({'ok': True})

        @app.post('/api/settings/polling')
        def update_polling():
            data = request.json or {}
            minutes = data.get('minutes', 30)
            if minutes in self.service.POLLING_OPTIONS:
                self.service.update_polling_interval(minutes)
            return self._json_response({'ok': True})

        @app.post('/api/settings/threshold')
        def set_threshold():
            data = request.json or {}
            key = data.get('key', '')
            value = int(data.get('value', 0))
            if key == '5h':
                self.notification_service.set_threshold_5h(value)
            elif key == '7d':
                self.notification_service.set_threshold_7d(value)
            elif key == 'extra':
                self.notification_service.set_threshold_extra(value)
            return self._json_response({'ok': True})

        @app.post('/api/settings/startup')
        def set_startup():
            data = request.json or {}
            enabled = data.get('enabled', False)
            self._set_startup(enabled)
            return self._json_response({'ok': True})

        @app.post('/api/hide')
        def hide_window():
            """Called by JS when window loses focus."""
            if not self._widget_mode:
                self.hide_browser()
            return self._json_response({'ok': True})

        @app.route('/api/mode')
        def get_mode():
            return self._json_response({
                'mode': 'widget' if self._widget_mode else 'popup',
            })

        @app.post('/api/exit-widget')
        def exit_widget():
            """Exit widget mode, switch to popup, and hide window."""
            if self._on_exit_widget_callback:
                self._on_exit_widget_callback()
            # Switch back to popup mode URL before hiding
            if self._webview_window:
                try:
                    self._webview_window.load_url(
                        f'http://127.0.0.1:{self.port}?mode=popup'
                    )
                except Exception:
                    pass
            self._position_bottom_right()
            self.hide_browser()
            return self._json_response({'ok': True})

    # ── Data serialization ──

    def _get_usage(self) -> dict:
        s = self.service
        usage = s.usage
        result = {
            'is_authenticated': s.is_authenticated,
            'is_awaiting_code': s.is_awaiting_code,
            'last_error': s.last_error,
            'last_updated': s.last_updated.isoformat() if s.last_updated else None,
            'account_email': s.account_email,
            'pct_5h': s.pct_5h,
            'pct_7d': s.pct_7d,
            'util_5h': None,
            'util_7d': None,
            'reset_5h': None,
            'reset_7d': None,
            'opus_util': None,
            'sonnet_util': None,
            'extra_enabled': False,
            'extra_util': None,
            'extra_used_str': '',
            'extra_limit_str': '',
        }
        if usage:
            if usage.five_hour:
                result['util_5h'] = usage.five_hour.utilization
                if usage.five_hour.resets_at_date:
                    result['reset_5h'] = usage.five_hour.resets_at_date.isoformat()
            if usage.seven_day:
                result['util_7d'] = usage.seven_day.utilization
                if usage.seven_day.resets_at_date:
                    result['reset_7d'] = usage.seven_day.resets_at_date.isoformat()
            if usage.seven_day_opus and usage.seven_day_opus.utilization is not None:
                result['opus_util'] = usage.seven_day_opus.utilization
            if usage.seven_day_sonnet and usage.seven_day_sonnet.utilization is not None:
                result['sonnet_util'] = usage.seven_day_sonnet.utilization
            if usage.extra_usage and usage.extra_usage.is_enabled:
                from models import ExtraUsage
                result['extra_enabled'] = True
                result['extra_util'] = usage.extra_usage.utilization
                result['extra_used_str'] = (
                    ExtraUsage.format_usd(usage.extra_usage.used_credits_amount)
                    if usage.extra_usage.used_credits_amount is not None else ''
                )
                result['extra_limit_str'] = (
                    ExtraUsage.format_usd(usage.extra_usage.monthly_limit_amount)
                    if usage.extra_usage.monthly_limit_amount is not None else ''
                )
        return result

    def _get_history(self, range_label: str) -> list:
        from models import TimeRange
        tr_map = {tr.label: tr for tr in TimeRange}
        tr = tr_map.get(range_label)
        if not tr:
            return []
        points = self.history_service.downsampled_points(tr)
        return [
            {'timestamp': p.timestamp.isoformat(), 'pct_5h': p.pct_5h, 'pct_7d': p.pct_7d}
            for p in points
        ]

    def _get_settings(self) -> dict:
        return {
            'startup_enabled': self._is_startup_enabled(),
            'polling_minutes': self.service.polling_minutes,
            'threshold_5h': self.notification_service.threshold_5h,
            'threshold_7d': self.notification_service.threshold_7d,
            'threshold_extra': self.notification_service.threshold_extra,
            'account_email': self.service.account_email,
        }

    # ── Startup registry ──

    @staticmethod
    def _is_startup_enabled() -> bool:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ,
            )
            try:
                winreg.QueryValueEx(key, "ClaudeUsageBar")
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    @staticmethod
    def _set_startup(enabled: bool):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            if enabled:
                exe_path = sys.executable
                winreg.SetValueEx(key, "ClaudeUsageBar", 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(key, "ClaudeUsageBar")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    # ── Server & Webview ──

    def start_server(self):
        """Start the Bottle server in a daemon thread."""
        def _run():
            self.app.run(host='127.0.0.1', port=self.port, quiet=True)
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _get_work_area(self):
        """Get the work area (excluding taskbar) in physical pixels."""
        try:
            import ctypes
            import ctypes.wintypes
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
            return rect.right, rect.bottom
        except Exception:
            return 1920, 1040

    def run_webview_main(self):
        """Create and run pywebview on the MAIN thread. Blocks until shutdown."""
        work_w, work_h = self._get_work_area()
        win_w, win_h = 420, 560

        # Physical pixel position for Win32 SetWindowPos
        phys_x = work_w - win_w
        phys_y = work_h - win_h

        mode = 'widget' if self._widget_mode else 'popup'
        url = f'http://127.0.0.1:{self.port}?mode={mode}'

        self._webview_window = webview.create_window(
            'Claude Usage',
            url=url,
            width=win_w,
            height=win_h,
            frameless=True,
            easy_drag=True,
        )

        def _on_closing():
            if self._webview_window:
                self._webview_window.hide()
                self._webview_visible = False
            return False  # Prevent actual destruction

        self._webview_window.events.closing += _on_closing

        def _on_shown():
            """Move window to bottom-right using the window's own monitor info."""
            try:
                import ctypes
                import ctypes.wintypes

                class MONITORINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", ctypes.wintypes.DWORD),
                        ("rcMonitor", ctypes.wintypes.RECT),
                        ("rcWork", ctypes.wintypes.RECT),
                        ("dwFlags", ctypes.wintypes.DWORD),
                    ]

                user32 = ctypes.windll.user32
                user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
                user32.FindWindowW.restype = ctypes.wintypes.HWND

                hwnd = user32.FindWindowW(None, 'Claude Usage')
                if not hwnd:
                    return

                # Get actual window size
                wr = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(wr))
                actual_w = wr.right - wr.left
                actual_h = wr.bottom - wr.top

                # Get work area of the monitor the window is on
                monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                user32.GetMonitorInfoW(monitor, ctypes.byref(mi))

                x = mi.rcWork.right - actual_w
                y = mi.rcWork.bottom - actual_h
                user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004)

                # Apply topmost if widget mode is active
                if self._widget_mode:
                    HWND_TOPMOST = -1
                    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0002 | 0x0001)
            except Exception:
                pass

        self._webview_window.events.shown += _on_shown

        storage = os.path.join(
            os.environ.get('LOCALAPPDATA', ''),
            'ClaudeUsageBar', 'WebView2',
        )
        webview.start(storage_path=storage)  # Blocks on main thread
        self._webview_window = None

    def is_browser_alive(self) -> bool:
        return self._webview_window is not None

    def show_browser(self):
        if self._webview_window:
            try:
                self._webview_window.show()
                self._webview_visible = True
            except Exception:
                pass

    def hide_browser(self):
        if self._webview_window:
            try:
                self._webview_window.hide()
                self._webview_visible = False
            except Exception:
                pass

    def toggle_browser(self):
        if self._webview_visible:
            self.hide_browser()
        else:
            self.show_browser()

    def close_browser(self):
        self.hide_browser()

    def enter_widget_mode(self):
        """Switch to widget mode: always visible, topmost, draggable."""
        self._widget_mode = True
        if self._webview_window:
            try:
                self._webview_window.load_url(
                    f'http://127.0.0.1:{self.port}?mode=widget'
                )
                self._webview_window.show()
                self._webview_visible = True
                self._set_topmost(True)
            except Exception:
                pass

    def exit_widget_mode(self):
        """Switch back to popup mode."""
        self._widget_mode = False
        if self._webview_window:
            try:
                self._webview_window.load_url(
                    f'http://127.0.0.1:{self.port}?mode=popup'
                )
                self._set_topmost(False)
                self._position_bottom_right()
            except Exception:
                pass

    def _set_topmost(self, topmost: bool):
        """Set or clear HWND_TOPMOST on the webview window."""
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            user32.FindWindowW.restype = ctypes.wintypes.HWND
            hwnd = user32.FindWindowW(None, 'Claude Usage')
            if not hwnd:
                return
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            insert_after = HWND_TOPMOST if topmost else HWND_NOTOPMOST
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        except Exception:
            pass

    def _position_bottom_right(self):
        """Reposition the window to bottom-right corner."""
        try:
            import ctypes
            import ctypes.wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.wintypes.DWORD),
                    ("rcMonitor", ctypes.wintypes.RECT),
                    ("rcWork", ctypes.wintypes.RECT),
                    ("dwFlags", ctypes.wintypes.DWORD),
                ]

            user32 = ctypes.windll.user32
            user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            user32.FindWindowW.restype = ctypes.wintypes.HWND
            hwnd = user32.FindWindowW(None, 'Claude Usage')
            if not hwnd:
                return
            wr = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(wr))
            actual_w = wr.right - wr.left
            actual_h = wr.bottom - wr.top
            monitor = user32.MonitorFromWindow(hwnd, 2)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(monitor, ctypes.byref(mi))
            x = mi.rcWork.right - actual_w
            y = mi.rcWork.bottom - actual_h
            user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004)
        except Exception:
            pass

    def shutdown_browser(self):
        """Destroy the webview window (causes run_webview_main to return)."""
        if self._webview_window:
            try:
                self._webview_window.events.closing.clear()
                self._webview_window.destroy()
            except Exception:
                pass
            self._webview_window = None
