"""Usage history persistence and downsampling."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone, timedelta
from math import floor
from pathlib import Path
from typing import List, Optional

from models import UsageDataPoint, TimeRange


class HistoryService:
    RETENTION_DAYS = 30
    FLUSH_INTERVAL = 300  # 5 minutes

    def __init__(self):
        self.data_points: List[UsageDataPoint] = []
        self._dirty = False
        self._flush_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._history_file = (
            Path.home() / ".config" / "claude-usage-bar" / "history.json"
        )

    def load_history(self):
        if not self._history_file.exists():
            return
        try:
            data = json.loads(self._history_file.read_text(encoding="utf-8"))
            points = [UsageDataPoint.from_dict(d) for d in data.get("data_points", [])]
            self.data_points = self._pruned(points)
        except Exception:
            # Corrupt file - rename and start fresh
            backup = self._history_file.with_suffix(".bak.json")
            try:
                if backup.exists():
                    backup.unlink()
                self._history_file.rename(backup)
            except OSError:
                pass
            self.data_points = []

    def record_data_point(self, pct_5h: float, pct_7d: float):
        point = UsageDataPoint(pct_5h=pct_5h, pct_7d=pct_7d)
        with self._lock:
            self.data_points.append(point)
            self._dirty = True
        self._start_flush_timer()

    def flush_to_disk(self):
        with self._lock:
            if not self._dirty:
                return
            self.data_points = self._pruned(self.data_points)
            data = {"data_points": [p.to_dict() for p in self.data_points]}

        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._history_file.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

        with self._lock:
            self._dirty = False
            if self._flush_timer:
                self._flush_timer.cancel()
                self._flush_timer = None

    def downsampled_points(self, time_range: TimeRange) -> List[UsageDataPoint]:
        now = datetime.now(timezone.utc)
        range_start = now - timedelta(seconds=time_range.interval)

        with self._lock:
            all_points = [p for p in self.data_points if p.timestamp >= range_start]

        if not all_points:
            return []

        if len(all_points) <= time_range.target_points:
            return all_points

        bucket_count = time_range.target_points
        bucket_duration = time_range.interval / bucket_count

        buckets: List[List[UsageDataPoint]] = [[] for _ in range(bucket_count)]

        for point in all_points:
            offset = (point.timestamp - range_start).total_seconds()
            idx = int(offset / bucket_duration)
            idx = max(0, min(bucket_count - 1, idx))
            buckets[idx].append(point)

        result = []
        for bucket in buckets:
            if not bucket:
                continue
            # Use max to preserve peaks (not average which hides spikes)
            max_5h = max(p.pct_5h for p in bucket)
            max_7d = max(p.pct_7d for p in bucket)
            # Use timestamp of the peak point
            peak = max(bucket, key=lambda p: p.pct_5h + p.pct_7d)
            result.append(UsageDataPoint(
                timestamp=peak.timestamp,
                pct_5h=max_5h,
                pct_7d=max_7d,
            ))
        return result

    def _pruned(self, points: List[UsageDataPoint]) -> List[UsageDataPoint]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.RETENTION_DAYS)
        return [p for p in points if p.timestamp >= cutoff]

    def _start_flush_timer(self):
        if self._flush_timer is not None:
            return
        self._flush_timer = threading.Timer(self.FLUSH_INTERVAL, self.flush_to_disk)
        self._flush_timer.daemon = True
        self._flush_timer.start()
