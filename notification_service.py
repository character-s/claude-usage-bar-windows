"""Windows toast notifications for usage threshold alerts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, List, Tuple


class NotificationService:
    def __init__(self):
        self.threshold_5h: int = 0
        self.threshold_7d: int = 0
        self.threshold_extra: int = 0

        self._prev_5h: Optional[float] = None
        self._prev_7d: Optional[float] = None
        self._prev_extra: Optional[float] = None

        self._load_thresholds()

    def set_threshold_5h(self, value: int):
        self.threshold_5h = max(0, min(100, value))
        self._prev_5h = None
        self._save_thresholds()

    def set_threshold_7d(self, value: int):
        self.threshold_7d = max(0, min(100, value))
        self._prev_7d = None
        self._save_thresholds()

    def set_threshold_extra(self, value: int):
        self.threshold_extra = max(0, min(100, value))
        self._prev_extra = None
        self._save_thresholds()

    def check_and_notify(self, pct_5h: float, pct_7d: float, pct_extra: float):
        current_5h = pct_5h * 100
        current_7d = pct_7d * 100
        current_extra = pct_extra * 100

        prev_5h = self._prev_5h or 0
        prev_7d = self._prev_7d or 0
        prev_extra = self._prev_extra or 0

        alerts = _crossed_thresholds(
            self.threshold_5h, self.threshold_7d, self.threshold_extra,
            prev_5h, prev_7d, prev_extra,
            current_5h, current_7d, current_extra,
        )

        self._prev_5h = current_5h
        self._prev_7d = current_7d
        self._prev_extra = current_extra

        for window, pct in alerts:
            self._send_notification(window, pct)

    def _send_notification(self, window: str, pct: int):
        try:
            from winotify import Notification
            toast = Notification(
                app_id="Claude Usage Bar",
                title="Claude Usage",
                msg=f"{window} usage has reached {pct}%",
            )
            toast.show()
        except Exception as e:
            print(f"[Notification] Failed: {e}")

    def _settings_file(self) -> Path:
        return Path.home() / ".config" / "claude-usage-bar" / "settings.json"

    def _load_thresholds(self):
        f = self._settings_file()
        if not f.exists():
            return
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            self.threshold_5h = max(0, min(100, data.get("threshold_5h", 0)))
            self.threshold_7d = max(0, min(100, data.get("threshold_7d", 0)))
            self.threshold_extra = max(0, min(100, data.get("threshold_extra", 0)))
        except Exception:
            pass

    def _save_thresholds(self):
        f = self._settings_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        settings = {}
        if f.exists():
            try:
                settings = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        settings["threshold_5h"] = self.threshold_5h
        settings["threshold_7d"] = self.threshold_7d
        settings["threshold_extra"] = self.threshold_extra
        f.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _crossed_thresholds(
    t5h: int, t7d: int, textra: int,
    prev5h: float, prev7d: float, prev_extra: float,
    cur5h: float, cur7d: float, cur_extra: float,
) -> List[Tuple[str, int]]:
    alerts = []
    if t5h > 0 and cur5h >= t5h and prev5h < t5h:
        alerts.append(("5-hour", int(round(cur5h))))
    if t7d > 0 and cur7d >= t7d and prev7d < t7d:
        alerts.append(("7-day", int(round(cur7d))))
    if textra > 0 and cur_extra >= textra and prev_extra < textra:
        alerts.append(("Extra usage", int(round(cur_extra))))
    return alerts
