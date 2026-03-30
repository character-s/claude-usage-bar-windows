"""ChatGPT Codex session authentication and usage API polling service."""

from __future__ import annotations

import json
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

import requests

from models import CodexUsageResponse


_CREDENTIALS_FILE = Path.home() / ".config" / "claude-usage-bar" / "codex_credentials.json"
_USAGE_CACHE_FILE = Path.home() / ".config" / "claude-usage-bar" / "codex_usage_cache.json"


class CodexService:
    SESSION_URL = "https://chatgpt.com/api/auth/session"
    USAGE_ENDPOINT = "https://chatgpt.com/backend-api/wham/usage"

    DEFAULT_POLLING_MINUTES = 30
    MAX_BACKOFF = 3600

    def __init__(self):
        self.usage: Optional[CodexUsageResponse] = None
        self.last_error: Optional[str] = None
        self.last_updated: Optional[datetime] = None
        self.is_authenticated = False
        self.is_awaiting_token = False

        self._access_token: Optional[str] = None
        self._polling_minutes = self.DEFAULT_POLLING_MINUTES
        self._current_interval = self._polling_minutes * 60
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        self.on_update: Optional[Callable] = None

        # Try to load saved token and cached usage
        self._load_token()
        self._load_usage_cache()

    # -- Properties --

    @property
    def pct_primary(self) -> float:
        if self.usage and self.usage.primary_window and self.usage.primary_window.used_percent is not None:
            return self.usage.primary_window.used_percent / 100.0
        return 0.0

    @property
    def pct_secondary(self) -> float:
        if self.usage and self.usage.secondary_window and self.usage.secondary_window.used_percent is not None:
            return self.usage.secondary_window.used_percent / 100.0
        return 0.0

    # -- Token persistence --

    def _load_token(self):
        if _CREDENTIALS_FILE.exists():
            try:
                data = json.loads(_CREDENTIALS_FILE.read_text(encoding="utf-8"))
                token = data.get("access_token", "")
                if token:
                    self._access_token = token
                    self.is_authenticated = True
            except Exception:
                pass

    def _save_token(self, token: str):
        _CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CREDENTIALS_FILE.write_text(
            json.dumps({"access_token": token}, indent=2), encoding="utf-8"
        )

    def _delete_token(self):
        self._access_token = None
        if _CREDENTIALS_FILE.exists():
            try:
                _CREDENTIALS_FILE.unlink()
            except Exception:
                pass

    # -- Usage cache --

    def _save_usage_cache(self):
        if not self.usage or not self.last_updated:
            return
        try:
            data = {
                'last_updated': self.last_updated.isoformat(),
                'primary_window': None,
                'secondary_window': None,
            }
            pw = self.usage.primary_window
            if pw:
                data['primary_window'] = {
                    'used_percent': pw.used_percent,
                    'limit_window_seconds': pw.limit_window_seconds,
                    'reset_after_seconds': pw.reset_after_seconds,
                }
            sw = self.usage.secondary_window
            if sw:
                data['secondary_window'] = {
                    'used_percent': sw.used_percent,
                    'limit_window_seconds': sw.limit_window_seconds,
                    'reset_after_seconds': sw.reset_after_seconds,
                }
            _USAGE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _USAGE_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_usage_cache(self):
        if not self.is_authenticated or not _USAGE_CACHE_FILE.exists():
            return
        try:
            data = json.loads(_USAGE_CACHE_FILE.read_text(encoding="utf-8"))
            self.usage = CodexUsageResponse.from_dict({'rate_limit': data})
            ts = data.get('last_updated')
            if ts:
                self.last_updated = datetime.fromisoformat(ts)
        except Exception:
            pass

    # -- Auth via browser --

    def start_login(self):
        """Open chatgpt.com/api/auth/session in the default browser.
        User copies the accessToken from the JSON and pastes it in the app.
        """
        webbrowser.open(self.SESSION_URL)
        self.is_awaiting_token = True
        self._notify_update()

    def submit_token(self, raw_token: str) -> bool:
        """User pastes the accessToken or the entire session JSON."""
        token = self._extract_token(raw_token)
        if not token:
            self.last_error = "Could not find accessToken"
            return False

        # Quick validation: try to fetch usage with this token
        try:
            resp = requests.get(
                self.USAGE_ENDPOINT,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if resp.status_code != 200:
                if resp.status_code in (401, 403):
                    self.last_error = "Invalid token -- please try again"
                elif resp.status_code == 429:
                    self.last_error = "Rate limited -- please wait and try again"
                else:
                    self.last_error = f"Validation failed (HTTP {resp.status_code})"
                return False
        except Exception as e:
            self.last_error = f"Validation failed: {e}"
            return False

        self._access_token = token
        self._save_token(token)
        self.is_authenticated = True
        self.is_awaiting_token = False
        self.last_error = None

        # Parse the validation response as initial usage data
        try:
            data = resp.json()
            self.usage = CodexUsageResponse.from_dict(data)
            self.last_updated = datetime.now(timezone.utc)
        except Exception:
            pass

        self.start_polling()
        self._notify_update()
        return True

    def cancel_login(self):
        self.is_awaiting_token = False
        self._notify_update()

    def sign_out(self):
        self._delete_token()
        self.is_authenticated = False
        self.usage = None
        self.last_updated = None
        self.last_error = None
        self.stop_polling()
        self._notify_update()

    # -- Polling --

    def update_polling_interval(self, minutes: int):
        """Update the polling interval (called when user changes settings)."""
        self._polling_minutes = minutes
        self._current_interval = minutes * 60
        if self.is_authenticated:
            self._schedule_timer()

    def start_polling(self):
        if not self.is_authenticated:
            return
        threading.Thread(target=self.fetch_usage, daemon=True).start()
        self._schedule_timer()

    def stop_polling(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _schedule_timer(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()

            def _poll():
                if self.is_authenticated:
                    self.fetch_usage()
                self._schedule_timer()

            self._timer = threading.Timer(self._current_interval, _poll)
            self._timer.daemon = True
            self._timer.start()

    # -- API Fetch --

    def fetch_usage(self):
        if not self._access_token:
            self.last_error = "Not signed in"
            self.is_authenticated = False
            self._notify_update()
            return

        try:
            resp = requests.get(
                self.USAGE_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                },
                timeout=30,
            )
        except Exception as e:
            self.last_error = str(e)
            self._notify_update()
            return

        if resp.status_code in (401, 403):
            self.last_error = "Session expired -- please sign in again"
            self.is_authenticated = False
            self._delete_token()
            self.stop_polling()
            self._notify_update()
            return

        if resp.status_code == 429:
            self._current_interval = min(
                self._current_interval * 2, self.MAX_BACKOFF
            )
            self.last_error = f"Rate limited -- backing off to {int(self._current_interval)}s"
            self._schedule_timer()
            self._notify_update()
            return

        if resp.status_code != 200:
            self.last_error = f"HTTP {resp.status_code}"
            self._notify_update()
            return

        try:
            data = resp.json()
            self.usage = CodexUsageResponse.from_dict(data)
            self.last_error = None
            self.last_updated = datetime.now(timezone.utc)
            self._save_usage_cache()

            base_interval = self._polling_minutes * 60
            if self._current_interval != base_interval:
                self._current_interval = base_interval
                self._schedule_timer()
        except Exception as e:
            self.last_error = str(e)

        self._notify_update()

    @staticmethod
    def _extract_token(raw: str) -> Optional[str]:
        """Extract accessToken from raw input.

        Accepts either:
        - The full session JSON (extracts accessToken field)
        - A bare token string
        """
        text = raw.strip()
        if not text:
            return None

        # Try parsing as JSON first
        if text.startswith('{'):
            try:
                data = json.loads(text)
                token = data.get("accessToken") or data.get("access_token")
                if token and isinstance(token, str):
                    return token
            except (json.JSONDecodeError, ValueError):
                pass

        # Otherwise treat as bare token
        return text if len(text) > 20 else None

    def _notify_update(self):
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                pass
