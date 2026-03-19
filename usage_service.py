"""OAuth PKCE authentication and usage API polling service."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable, List
from urllib.parse import urlencode

import requests

from credentials_store import CredentialsStore, StoredCredentials
from models import UsageResponse


class UsageService:
    AUTHORIZE_ENDPOINT = "https://claude.ai/oauth/authorize"
    USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
    USERINFO_ENDPOINT = "https://api.anthropic.com/api/oauth/userinfo"
    TOKEN_ENDPOINT = "https://platform.claude.com/v1/oauth/token"
    REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
    CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    DEFAULT_SCOPES = ["user:profile", "user:inference"]

    DEFAULT_POLLING_MINUTES = 30
    POLLING_OPTIONS = [5, 15, 30, 60]
    MAX_BACKOFF = 3600  # 1 hour

    def __init__(self):
        self.credentials_store = CredentialsStore()
        self.usage: Optional[UsageResponse] = None
        self.last_error: Optional[str] = None
        self.last_updated: Optional[datetime] = None
        self.is_authenticated = self.credentials_store.load() is not None
        self.is_awaiting_code = False
        self.account_email: Optional[str] = None

        self._polling_minutes = self._load_polling_minutes()
        self._current_interval = self._polling_minutes * 60
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        # PKCE state
        self._code_verifier: Optional[str] = None
        self._oauth_state: Optional[str] = None

        # Callbacks
        self.on_update: Optional[Callable] = None  # called when usage changes

    # -- Properties --

    @property
    def pct_5h(self) -> float:
        if self.usage and self.usage.five_hour and self.usage.five_hour.utilization is not None:
            return self.usage.five_hour.utilization / 100.0
        return 0.0

    @property
    def pct_7d(self) -> float:
        if self.usage and self.usage.seven_day and self.usage.seven_day.utilization is not None:
            return self.usage.seven_day.utilization / 100.0
        return 0.0

    @property
    def pct_extra(self) -> float:
        if self.usage and self.usage.extra_usage and self.usage.extra_usage.utilization is not None:
            return self.usage.extra_usage.utilization / 100.0
        return 0.0

    @property
    def reset_5h(self) -> Optional[datetime]:
        return self.usage.five_hour.resets_at_date if self.usage and self.usage.five_hour else None

    @property
    def reset_7d(self) -> Optional[datetime]:
        return self.usage.seven_day.resets_at_date if self.usage and self.usage.seven_day else None

    @property
    def polling_minutes(self) -> int:
        return self._polling_minutes

    def update_polling_interval(self, minutes: int):
        self._polling_minutes = minutes
        self._current_interval = minutes * 60
        self._save_polling_minutes(minutes)
        if self.is_authenticated:
            self._schedule_timer()
            threading.Thread(target=self.fetch_usage, daemon=True).start()

    # -- Polling --

    def start_polling(self):
        if not self.is_authenticated:
            return
        threading.Thread(target=self._initial_poll, daemon=True).start()
        self._schedule_timer()

    def stop_polling(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _initial_poll(self):
        self.fetch_usage()
        if not self.account_email:
            self.fetch_profile()

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

    # -- OAuth PKCE --

    def start_oauth_flow(self):
        self._code_verifier = self._generate_code_verifier()
        challenge = self._generate_code_challenge(self._code_verifier)
        self._oauth_state = self._generate_code_verifier()

        params = {
            "code": "true",
            "client_id": self.CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.REDIRECT_URI,
            "scope": " ".join(self.DEFAULT_SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": self._oauth_state,
        }
        url = f"{self.AUTHORIZE_ENDPOINT}?{urlencode(params)}"
        webbrowser.open(url)
        self.is_awaiting_code = True

    def submit_oauth_code(self, raw_code: str) -> bool:
        raw_code = raw_code.strip()
        parts = raw_code.split("#", 1)
        code = parts[0]

        if len(parts) > 1:
            returned_state = parts[1]
            if returned_state != self._oauth_state:
                self.last_error = "OAuth state mismatch -- try again"
                self.is_awaiting_code = False
                self._code_verifier = None
                self._oauth_state = None
                return False

        if not self._code_verifier:
            self.last_error = "No pending OAuth flow"
            self.is_awaiting_code = False
            return False

        body = {
            "grant_type": "authorization_code",
            "code": code,
            "state": self._oauth_state or "",
            "client_id": self.CLIENT_ID,
            "redirect_uri": self.REDIRECT_URI,
            "code_verifier": self._code_verifier,
        }

        try:
            resp = requests.post(
                self.TOKEN_ENDPOINT,
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code != 200:
                self.last_error = f"Token exchange failed: HTTP {resp.status_code}"
                return False

            data = resp.json()
            creds = self._credentials_from_json(data)
            if not creds:
                self.last_error = "Could not parse token response"
                return False

            self.credentials_store.save(creds)
            self.is_authenticated = True
            self.is_awaiting_code = False
            self.last_error = None
            self._code_verifier = None
            self._oauth_state = None

            self.fetch_profile()
            self.start_polling()
            return True

        except Exception as e:
            self.last_error = f"Token exchange error: {e}"
            return False

    def sign_out(self):
        self.credentials_store.delete()
        self.is_authenticated = False
        self.usage = None
        self.last_updated = None
        self.account_email = None
        self.last_error = None
        self.stop_polling()
        self._notify_update()

    # -- API Fetch --

    def fetch_usage(self):
        creds = self.credentials_store.load()
        if not creds:
            self.last_error = "Not signed in"
            self.is_authenticated = False
            self._notify_update()
            return

        result = self._send_authorized_request(self.USAGE_ENDPOINT)
        if result is None:
            self._notify_update()
            return

        resp, status_code = result

        if status_code == 429:
            retry_after = None
            try:
                retry_after = float(resp.headers.get("Retry-After", self._current_interval))
            except (ValueError, TypeError):
                pass
            self._current_interval = min(
                max(retry_after or self._current_interval, self._current_interval * 2),
                self.MAX_BACKOFF,
            )
            self.last_error = f"Rate limited -- backing off to {int(self._current_interval)}s"
            self._schedule_timer()
            self._notify_update()
            return

        if status_code != 200:
            self.last_error = f"HTTP {status_code}"
            self._notify_update()
            return

        try:
            data = resp.json()
            decoded = UsageResponse.from_dict(data)
            self.usage = decoded.reconciled(self.usage)
            self.last_error = None
            self.last_updated = datetime.now(timezone.utc)

            base_interval = self._polling_minutes * 60
            if self._current_interval != base_interval:
                self._current_interval = base_interval
                self._schedule_timer()

        except Exception as e:
            self.last_error = str(e)

        self._notify_update()

    def fetch_profile(self):
        # Try local Claude config first
        local = self._load_local_profile()
        if local:
            self.account_email = local
            return

        result = self._send_authorized_request(self.USERINFO_ENDPOINT, expire_on_auth_failure=False)
        if result is None:
            return

        resp, status_code = result
        if status_code != 200:
            return

        try:
            data = resp.json()
            email = data.get("email", "")
            name = data.get("name", "")
            self.account_email = email if email else (name if name else None)
        except Exception:
            pass

    # -- Internal --

    def _send_authorized_request(
        self, url: str, expire_on_auth_failure: bool = True
    ) -> Optional[tuple]:
        creds = self.credentials_store.load()
        if not creds:
            self.last_error = "Not signed in"
            self.is_authenticated = False
            return None

        if creds.needs_refresh():
            if not self._refresh_credentials():
                if creds.is_expired():
                    if expire_on_auth_failure:
                        self._expire_session()
                    return None

        creds = self.credentials_store.load() or creds

        try:
            resp = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {creds.access_token}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
                timeout=30,
            )
        except Exception as e:
            self.last_error = str(e)
            return None

        if resp.status_code == 401:
            if self._refresh_credentials():
                creds = self.credentials_store.load()
                if creds:
                    try:
                        resp = requests.get(
                            url,
                            headers={
                                "Authorization": f"Bearer {creds.access_token}",
                                "anthropic-beta": "oauth-2025-04-20",
                            },
                            timeout=30,
                        )
                    except Exception as e:
                        self.last_error = str(e)
                        return None
                    if resp.status_code == 401:
                        if expire_on_auth_failure:
                            self._expire_session()
                        return None
                else:
                    if expire_on_auth_failure:
                        self._expire_session()
                    return None
            else:
                if expire_on_auth_failure:
                    self._expire_session()
                return None

        return (resp, resp.status_code)

    def _refresh_credentials(self) -> bool:
        creds = self.credentials_store.load()
        if not creds or not creds.has_refresh_token:
            return False

        body = {
            "grant_type": "refresh_token",
            "refresh_token": creds.refresh_token,
            "client_id": self.CLIENT_ID,
        }
        if creds.scopes:
            body["scope"] = " ".join(creds.scopes)

        try:
            resp = requests.post(
                self.TOKEN_ENDPOINT,
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code != 200:
                return False

            data = resp.json()
            updated = self._credentials_from_json(data, fallback=creds)
            if not updated:
                return False

            self.credentials_store.save(updated)
            self.is_authenticated = True
            return True

        except Exception:
            return False

    def _expire_session(self):
        self.credentials_store.delete()
        self.is_authenticated = False
        self.usage = None
        self.last_updated = None
        self.account_email = None
        self.stop_polling()
        self.last_error = "Session expired -- please sign in again"

    def _credentials_from_json(
        self, data: dict, fallback: Optional[StoredCredentials] = None
    ) -> Optional[StoredCredentials]:
        access_token = data.get("access_token", "")
        if not access_token:
            return None

        scope_str = data.get("scope", "")
        scopes = scope_str.split() if scope_str else (
            fallback.scopes if fallback else self.DEFAULT_SCOPES
        )

        expires_at = None
        expires_in = data.get("expires_in")
        if expires_in is not None:
            try:
                expires_at = (datetime.now(timezone.utc) + timedelta(seconds=float(expires_in))).isoformat()
            except (ValueError, TypeError):
                pass
        if expires_at is None and fallback:
            expires_at = fallback.expires_at

        return StoredCredentials(
            access_token=access_token,
            refresh_token=data.get("refresh_token") or (fallback.refresh_token if fallback else None),
            expires_at=expires_at,
            scopes=scopes,
        )

    @staticmethod
    def _load_local_profile() -> Optional[str]:
        claude_json = Path.home() / ".claude.json"
        if not claude_json.exists():
            return None
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            account = data.get("oauthAccount", {})
            email = account.get("emailAddress", "")
            if email:
                return email
            name = account.get("displayName", "")
            return name if name else None
        except Exception:
            return None

    @staticmethod
    def _generate_code_verifier() -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")

    @staticmethod
    def _generate_code_challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def _notify_update(self):
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                pass

    def _load_polling_minutes(self) -> int:
        settings_file = Path.home() / ".config" / "claude-usage-bar" / "settings.json"
        if settings_file.exists():
            try:
                data = json.loads(settings_file.read_text(encoding="utf-8"))
                minutes = data.get("polling_minutes", self.DEFAULT_POLLING_MINUTES)
                if minutes in self.POLLING_OPTIONS:
                    return minutes
            except Exception:
                pass
        return self.DEFAULT_POLLING_MINUTES

    def _save_polling_minutes(self, minutes: int):
        settings_file = Path.home() / ".config" / "claude-usage-bar" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings = {}
        if settings_file.exists():
            try:
                settings = json.loads(settings_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        settings["polling_minutes"] = minutes
        settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
