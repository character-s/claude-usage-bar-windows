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

from version import VERSION, GITHUB_REPO

if TYPE_CHECKING:
    from usage_service import UsageService
    from history_service import HistoryService
    from notification_service import NotificationService
    from codex_service import CodexService


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
        codex_service: Optional[CodexService] = None,
    ):
        self.service = service
        self.history_service = history_service
        self.notification_service = notification_service
        self.codex_service: Optional[CodexService] = codex_service
        self._quit_callback: Optional[callable] = None
        self._on_exit_widget_callback: Optional[callable] = None

        self.app = Bottle()
        self._setup_routes()

        self.port = _find_free_port()
        self._webview_window: Optional[webview.Window] = None
        self._webview_visible = True
        self._widget_mode = False
        self._dpi_scale: float = 1.0  # physical / logical ratio, set after first show

        self._heal_startup_path()

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
            if self.codex_service and self.codex_service.is_authenticated:
                threading.Thread(target=self.codex_service.fetch_usage, daemon=True).start()
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
                if self.codex_service:
                    self.codex_service.update_polling_interval(minutes)
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

        @app.route('/api/window-pos')
        def get_window_pos():
            """Return current window position for JS drag."""
            pos = self._get_window_pos()
            return self._json_response(pos)

        @app.post('/api/move-window')
        def move_window():
            """Move window to absolute position."""
            data = request.json or {}
            x = int(data.get('x', 0))
            y = int(data.get('y', 0))
            self._move_window(x, y)
            return self._json_response({'ok': True})

        @app.post('/api/exit-widget')
        def exit_widget():
            """Exit widget mode, switch to popup, and hide window."""
            if self._on_exit_widget_callback:
                self._on_exit_widget_callback()
            self.hide_browser()
            self._position_bottom_right()
            return self._json_response({'ok': True})

        # -- Codex endpoints --

        @app.post('/api/codex/sign-in')
        def codex_sign_in():
            if self.codex_service:
                self.codex_service.start_login()
            return self._json_response({'ok': True})

        @app.post('/api/codex/submit-token')
        def codex_submit_token():
            data = request.json or {}
            token = data.get('token', '')
            if self.codex_service:
                success = self.codex_service.submit_token(token)
                return self._json_response({
                    'success': success,
                    'error': self.codex_service.last_error if not success else None,
                })
            return self._json_response({'success': False, 'error': 'Codex service not available'})

        @app.post('/api/codex/sign-out')
        def codex_sign_out():
            if self.codex_service:
                self.codex_service.sign_out()
            return self._json_response({'ok': True})

        @app.post('/api/settings/primary-provider')
        def set_primary_provider():
            data = request.json or {}
            provider = data.get('provider', 'claude')
            if provider in ('claude', 'codex'):
                self._save_primary_provider(provider)
            return self._json_response({'ok': True})

        @app.post('/api/settings/dual-mode')
        def set_dual_mode():
            data = request.json or {}
            enabled = bool(data.get('enabled', False))
            self._save_dual_mode(enabled)
            return self._json_response({'ok': True})

        @app.route('/api/version')
        def get_version():
            return self._json_response({
                'version': VERSION,
                'repo': GITHUB_REPO,
            })

        @app.post('/api/check-update')
        def check_update():
            return self._json_response(self._check_update())

        @app.post('/api/open-url')
        def open_url():
            import webbrowser
            data = request.json or {}
            url = str(data.get('url', ''))
            if url.startswith('https://') or url.startswith('http://'):
                webbrowser.open(url)
                return self._json_response({'ok': True})
            return self._json_response({'ok': False, 'error': 'invalid url'})

        @app.post('/api/resize')
        def resize_to_content():
            data = request.json or {}
            height = int(data.get('height', 0))
            if height > 0:
                # Clamp: min 300, max = screen work area height
                max_h = self._get_screen_work_height()
                height = max(300, min(height, max_h))
                self._resize_window(height)
            return self._json_response({'ok': True})

        # Static file route MUST be last (catch-all)
        @app.route('/<filepath:path>')
        def serve_static(filepath):
            return static_file(filepath, root=_web_dir())

    # ── Data serialization ──

    def _get_usage(self) -> dict:
        s = self.service
        usage = s.usage
        result = {
            'primary_provider': self._load_primary_provider(),
            'dual_mode': self._load_dual_mode(),
            'polling_minutes': s.polling_minutes,
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
            'design_util': None,
            'reset_design': None,
            'fable_util': None,
            'reset_fable': None,
            'fable_label': 'Fable',
            'extra_enabled': False,
            'extra_util': None,
            'extra_used_str': '',
            'extra_limit_str': '',
            # Codex fields
            'codex_authenticated': False,
            'codex_awaiting_token': False,
            'codex_last_error': None,
            'codex_last_updated': None,
            'codex_primary_pct': None,
            'codex_primary_reset': None,
            'codex_primary_label': '',
            'codex_secondary_pct': None,
            'codex_secondary_reset': None,
            'codex_secondary_label': '',
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
            if usage.seven_day_claude_design and usage.seven_day_claude_design.utilization is not None:
                result['design_util'] = usage.seven_day_claude_design.utilization
                if usage.seven_day_claude_design.resets_at_date:
                    result['reset_design'] = usage.seven_day_claude_design.resets_at_date.isoformat()
            if usage.seven_day_fable and usage.seven_day_fable.utilization is not None:
                result['fable_util'] = usage.seven_day_fable.utilization
                result['fable_label'] = usage.fable_label
                if usage.seven_day_fable.resets_at_date:
                    result['reset_fable'] = usage.seven_day_fable.resets_at_date.isoformat()
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
        # Codex data
        cs = self.codex_service
        if cs:
            result['codex_authenticated'] = cs.is_authenticated
            result['codex_awaiting_token'] = cs.is_awaiting_token
            result['codex_last_error'] = cs.last_error
            result['codex_last_updated'] = cs.last_updated.isoformat() if cs.last_updated else None
            if cs.usage:
                pw = cs.usage.primary_window
                if pw:
                    result['codex_primary_pct'] = pw.used_percent
                    result['codex_primary_label'] = pw.window_label
                    if pw.reset_at_date:
                        result['codex_primary_reset'] = pw.reset_at_date.isoformat()
                sw = cs.usage.secondary_window
                if sw:
                    result['codex_secondary_pct'] = sw.used_percent
                    result['codex_secondary_label'] = sw.window_label
                    if sw.reset_at_date:
                        result['codex_secondary_reset'] = sw.reset_at_date.isoformat()
        return result

    def _get_history(self, range_label: str) -> list:
        from models import TimeRange
        tr_map = {tr.label: tr for tr in TimeRange}
        tr = tr_map.get(range_label)
        if not tr:
            return []
        points = self.history_service.downsampled_points(tr)
        return [
            {
                'timestamp': p.timestamp.isoformat(),
                'pct_5h': p.pct_5h, 'pct_7d': p.pct_7d,
                'codex_primary': p.codex_primary, 'codex_secondary': p.codex_secondary,
            }
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
            'primary_provider': self._load_primary_provider(),
            'dual_mode': self._load_dual_mode(),
            'codex_authenticated': self.codex_service.is_authenticated if self.codex_service else False,
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
                winreg.SetValueEx(key, "ClaudeUsageBar", 0, winreg.REG_SZ, f'"{exe_path}" --silent')
            else:
                try:
                    winreg.DeleteValue(key, "ClaudeUsageBar")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    @staticmethod
    def _heal_startup_path():
        """If Run registry points to a different exe path, rewrite to current."""
        if not getattr(sys, 'frozen', False):
            return
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ | winreg.KEY_SET_VALUE,
            )
            try:
                existing, _ = winreg.QueryValueEx(key, "ClaudeUsageBar")
            except FileNotFoundError:
                winreg.CloseKey(key)
                return
            current_exe = os.path.normcase(os.path.abspath(sys.executable))
            expected = f'"{sys.executable}" --silent'
            # Extract registered exe path for comparison
            reg_exe = existing.split('"')[1] if existing.startswith('"') else existing.split()[0]
            reg_exe_norm = os.path.normcase(os.path.abspath(reg_exe))
            if reg_exe_norm != current_exe:
                winreg.SetValueEx(key, "ClaudeUsageBar", 0, winreg.REG_SZ, expected)
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

    def run_webview_main(self, hidden: bool = False):
        """Create and run pywebview on the MAIN thread. Blocks until shutdown."""
        work_w, work_h = self._get_work_area()
        win_w, win_h = 405, 600

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
            easy_drag=False,
            hidden=True,
        )

        def _on_closing():
            if self._webview_window:
                self._webview_window.hide()
                self._webview_visible = False
            return False  # Prevent actual destruction

        self._webview_window.events.closing += _on_closing

        def _on_loaded():
            """Position window after content loads, then show."""
            import time
            time.sleep(0.3)
            # Capture DPI scale from initial physical vs logical size
            if self._dpi_scale == 1.0:
                try:
                    import ctypes, ctypes.wintypes
                    hwnd = self._get_hwnd()
                    if hwnd:
                        wr = ctypes.wintypes.RECT()
                        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(wr))
                        phys_h = wr.bottom - wr.top
                        if phys_h > 0 and win_h > 0:
                            self._dpi_scale = phys_h / win_h
                except Exception:
                    pass
            self._position_bottom_right()

            if self._widget_mode:
                self._set_topmost(True)

            if not hidden:
                self._webview_window.show()
                self._webview_visible = True
                time.sleep(0.1)
                self._position_bottom_right()

        self._webview_window.events.loaded += _on_loaded

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
                # Ensure correct mode URL
                mode = 'widget' if self._widget_mode else 'popup'
                expected = f'http://127.0.0.1:{self.port}?mode={mode}'
                try:
                    current = self._webview_window.get_current_url() or ''
                except Exception:
                    current = ''
                if f'mode={mode}' not in current:
                    self._webview_window.load_url(expected)
                self._webview_window.show()
                self._webview_visible = True
                if not self._widget_mode:
                    self._position_bottom_right()
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

    def _get_hwnd(self):
        """Get the HWND for the webview window."""
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            user32.FindWindowW.restype = ctypes.wintypes.HWND
            return user32.FindWindowW(None, 'Claude Usage')
        except Exception:
            return None

    def _get_window_pos(self) -> dict:
        """Get current window position and DPI scale factor."""
        try:
            import ctypes
            import ctypes.wintypes
            hwnd = self._get_hwnd()
            if not hwnd:
                return {'x': 0, 'y': 0, 'dpi_scale': 1.0}
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            # Get DPI for the monitor this window is on
            try:
                dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                dpi_scale = dpi / 96.0
            except Exception:
                dpi_scale = 1.0
            return {'x': rect.left, 'y': rect.top, 'dpi_scale': dpi_scale}
        except Exception:
            return {'x': 0, 'y': 0, 'dpi_scale': 1.0}

    def _move_window(self, x: int, y: int):
        """Move window to absolute position."""
        try:
            import ctypes
            hwnd = self._get_hwnd()
            if not hwnd:
                return
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            ctypes.windll.user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER)
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
        """Reposition the window to bottom-right corner of PRIMARY monitor."""
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
            hwnd = self._get_hwnd()
            if not hwnd:
                return
            wr = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(wr))
            actual_w = wr.right - wr.left
            actual_h = wr.bottom - wr.top
            # Use primary monitor (point 0,0 is always on primary)
            MONITOR_DEFAULTTOPRIMARY = 1
            pt = ctypes.wintypes.POINT(0, 0)
            monitor = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY)
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

    # ── Primary provider settings ──

    @staticmethod
    def _load_primary_provider() -> str:
        settings_file = Path.home() / ".config" / "claude-usage-bar" / "settings.json"
        if settings_file.exists():
            try:
                data = json.loads(settings_file.read_text(encoding="utf-8"))
                p = data.get("primary_provider", "claude")
                if p in ("claude", "codex"):
                    return p
            except Exception:
                pass
        return "claude"

    @staticmethod
    def _save_primary_provider(provider: str):
        settings_file = Path.home() / ".config" / "claude-usage-bar" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings = {}
        if settings_file.exists():
            try:
                settings = json.loads(settings_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        settings["primary_provider"] = provider
        settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    @staticmethod
    def _load_dual_mode() -> bool:
        settings_file = Path.home() / ".config" / "claude-usage-bar" / "settings.json"
        if settings_file.exists():
            try:
                data = json.loads(settings_file.read_text(encoding="utf-8"))
                return bool(data.get("dual_mode", False))
            except Exception:
                pass
        return False

    @staticmethod
    def _save_dual_mode(enabled: bool):
        settings_file = Path.home() / ".config" / "claude-usage-bar" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings = {}
        if settings_file.exists():
            try:
                settings = json.loads(settings_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        settings["dual_mode"] = enabled
        settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def _get_screen_work_height(self) -> int:
        """Return the screen work-area height in logical (CSS) pixels."""
        try:
            import ctypes
            import ctypes.wintypes
            SPI_GETWORKAREA = 0x0030
            rc = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rc), 0)
            phys_h = rc.bottom - rc.top
            hwnd = self._get_hwnd()
            if hwnd:
                dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                scale = dpi / 96.0
            else:
                scale = 1.0
            return int(phys_h / scale)
        except Exception:
            return 1200  # fallback

    def _check_update(self) -> dict:
        """Query GitHub Releases API for the latest release and compare with current version."""
        import urllib.request
        import urllib.error

        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"claude-usage-bar/{VERSION}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {'ok': False, 'error': f'GitHub API HTTP {e.code}'}
        except Exception as e:
            return {'ok': False, 'error': f'Network error: {e}'}

        tag = (data.get('tag_name') or '').lstrip('v').strip()
        if not tag:
            return {'ok': False, 'error': 'No release found'}

        try:
            latest_t = tuple(int(x) for x in tag.split('.'))
            current_t = tuple(int(x) for x in VERSION.split('.'))
            has_update = latest_t > current_t
        except Exception:
            has_update = tag != VERSION

        return {
            'ok': True,
            'current': VERSION,
            'latest': tag,
            'has_update': has_update,
            'release_url': data.get('html_url', ''),
            'release_name': data.get('name', ''),
            'published_at': data.get('published_at', ''),
        }

    def _resize_window(self, new_height: int):
        """Resize the webview window height only, preserving current width.

        new_height is in logical (CSS) pixels. We query DPI directly from
        the window handle to convert to physical pixels for SetWindowPos.
        Skips the SetWindowPos call entirely when the target height is
        within 2 physical pixels of the current height (no-op resize).
        """
        try:
            import ctypes
            import ctypes.wintypes
            hwnd = self._get_hwnd()
            if not hwnd:
                return
            wr = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(wr))
            cur_w = wr.right - wr.left
            cur_h = wr.bottom - wr.top
            try:
                dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                scale = dpi / 96.0
            except Exception:
                scale = self._dpi_scale
            phys_h = int(new_height * scale)
            # Skip no-op resizes to avoid flicker and unnecessary SetWindowPos calls
            if abs(phys_h - cur_h) < 2:
                return
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, cur_w, phys_h, SWP_NOMOVE | SWP_NOZORDER)
            if not self._widget_mode:
                self._position_bottom_right()
        except Exception:
            pass
