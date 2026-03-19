"""Data models for Claude Usage Bar."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Usage API response models
# ---------------------------------------------------------------------------

@dataclass
class UsageBucket:
    utilization: Optional[float] = None  # 0-100
    resets_at: Optional[str] = None

    @property
    def resets_at_date(self) -> Optional[datetime]:
        return _parse_reset_date(self.resets_at)

    def reconciled(self, previous: Optional[UsageBucket], reset_interval: float, now: datetime) -> UsageBucket:
        if self.resets_at_date is not None:
            return self
        if previous is None or previous.resets_at_date is None:
            return self
        resolved = _next_reset_date(previous.resets_at_date, reset_interval, now)
        return UsageBucket(utilization=self.utilization, resets_at=resolved.isoformat())

    @staticmethod
    def from_dict(d: Optional[dict]) -> Optional[UsageBucket]:
        if d is None:
            return None
        return UsageBucket(
            utilization=d.get("utilization"),
            resets_at=d.get("resets_at"),
        )


@dataclass
class ExtraUsage:
    is_enabled: bool = False
    utilization: Optional[float] = None
    used_credits: Optional[float] = None  # cents
    monthly_limit: Optional[float] = None  # cents

    @property
    def used_credits_amount(self) -> Optional[float]:
        return self.used_credits / 100.0 if self.used_credits is not None else None

    @property
    def monthly_limit_amount(self) -> Optional[float]:
        return self.monthly_limit / 100.0 if self.monthly_limit is not None else None

    @staticmethod
    def format_usd(amount: float) -> str:
        return f"${amount:,.2f}"

    @staticmethod
    def from_dict(d: Optional[dict]) -> Optional[ExtraUsage]:
        if d is None:
            return None
        return ExtraUsage(
            is_enabled=d.get("is_enabled", False),
            utilization=d.get("utilization"),
            used_credits=d.get("used_credits"),
            monthly_limit=d.get("monthly_limit"),
        )


@dataclass
class UsageResponse:
    five_hour: Optional[UsageBucket] = None
    seven_day: Optional[UsageBucket] = None
    seven_day_opus: Optional[UsageBucket] = None
    seven_day_sonnet: Optional[UsageBucket] = None
    extra_usage: Optional[ExtraUsage] = None

    def reconciled(self, previous: Optional[UsageResponse], now: Optional[datetime] = None) -> UsageResponse:
        if now is None:
            now = datetime.now(timezone.utc)
        return UsageResponse(
            five_hour=self.five_hour.reconciled(
                previous.five_hour if previous else None, 5 * 3600, now
            ) if self.five_hour else None,
            seven_day=self.seven_day.reconciled(
                previous.seven_day if previous else None, 7 * 86400, now
            ) if self.seven_day else None,
            seven_day_opus=self.seven_day_opus.reconciled(
                previous.seven_day_opus if previous else None, 7 * 86400, now
            ) if self.seven_day_opus else None,
            seven_day_sonnet=self.seven_day_sonnet.reconciled(
                previous.seven_day_sonnet if previous else None, 7 * 86400, now
            ) if self.seven_day_sonnet else None,
            extra_usage=self.extra_usage,
        )

    @staticmethod
    def from_dict(d: dict) -> UsageResponse:
        return UsageResponse(
            five_hour=UsageBucket.from_dict(d.get("five_hour")),
            seven_day=UsageBucket.from_dict(d.get("seven_day")),
            seven_day_opus=UsageBucket.from_dict(d.get("seven_day_opus")),
            seven_day_sonnet=UsageBucket.from_dict(d.get("seven_day_sonnet")),
            extra_usage=ExtraUsage.from_dict(d.get("extra_usage")),
        )


# ---------------------------------------------------------------------------
# History models
# ---------------------------------------------------------------------------

@dataclass
class UsageDataPoint:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pct_5h: float = 0.0
    pct_7d: float = 0.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "pct_5h": self.pct_5h,
            "pct_7d": self.pct_7d,
        }

    @staticmethod
    def from_dict(d: dict) -> UsageDataPoint:
        return UsageDataPoint(
            id=d.get("id", str(uuid.uuid4())),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            pct_5h=d["pct_5h"],
            pct_7d=d["pct_7d"],
        )


class TimeRange(Enum):
    HOUR_1 = ("1h", 3600, 120)
    HOUR_6 = ("6h", 6 * 3600, 180)
    DAY_1 = ("1d", 86400, 200)
    DAY_7 = ("7d", 7 * 86400, 200)
    DAY_30 = ("30d", 30 * 86400, 200)

    def __init__(self, label: str, interval: float, target_points: int):
        self.label = label
        self.interval = interval
        self.target_points = target_points


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_reset_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _next_reset_date(previous: datetime, reset_interval: float, now: datetime) -> datetime:
    if reset_interval <= 0 or previous > now:
        return previous
    elapsed = (now - previous).total_seconds()
    from math import floor
    step_count = floor(elapsed / reset_interval) + 1
    from datetime import timedelta
    return previous + timedelta(seconds=step_count * reset_interval)
