"""Credential storage for OAuth tokens."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List


@dataclass
class StoredCredentials:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601
    scopes: List[str] = None

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = ["user:profile", "user:inference"]

    @property
    def has_refresh_token(self) -> bool:
        return bool(self.refresh_token)

    def needs_refresh(self, leeway: float = 300) -> bool:
        if not self.has_refresh_token or not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return expires <= datetime.now(timezone.utc) + timedelta(seconds=leeway)
        except (ValueError, TypeError):
            return False

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return expires <= datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False


class CredentialsStore:
    def __init__(self, directory: Optional[Path] = None):
        if directory is None:
            directory = Path.home() / ".config" / "claude-usage-bar"
        self.directory = directory
        self.credentials_file = directory / "credentials.json"
        self.legacy_token_file = directory / "token"

    def save(self, credentials: StoredCredentials) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {
            "access_token": credentials.access_token,
            "refresh_token": credentials.refresh_token,
            "expires_at": credentials.expires_at,
            "scopes": credentials.scopes,
        }
        self.credentials_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Remove legacy token file if it exists
        if self.legacy_token_file.exists():
            self.legacy_token_file.unlink()

    def load(self, default_scopes: Optional[List[str]] = None) -> Optional[StoredCredentials]:
        if default_scopes is None:
            default_scopes = ["user:profile", "user:inference"]

        if self.credentials_file.exists():
            try:
                data = json.loads(self.credentials_file.read_text(encoding="utf-8"))
                return StoredCredentials(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    expires_at=data.get("expires_at"),
                    scopes=data.get("scopes", default_scopes),
                )
            except (json.JSONDecodeError, KeyError):
                pass

        # Try legacy token file
        if self.legacy_token_file.exists():
            try:
                token = self.legacy_token_file.read_text(encoding="utf-8").strip()
                if token:
                    return StoredCredentials(
                        access_token=token,
                        scopes=default_scopes,
                    )
            except OSError:
                pass

        return None

    def delete(self) -> None:
        for f in [self.credentials_file, self.legacy_token_file]:
            try:
                f.unlink()
            except FileNotFoundError:
                pass
