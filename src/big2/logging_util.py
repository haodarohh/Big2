"""Append-only JSONL logger for one game session, used to record every
AI decision call (request options, raw response, retry index) for later
review of how jev played."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class GameLogger:
    def __init__(self, log_dir: Path | str = "logs") -> None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = log_dir / f"game-{timestamp}.jsonl"
        self._ai_stats = {"calls": 0, "errors": 0, "illegal": 0, "turns_exhausted": 0}

    def log(self, event: dict[str, Any]) -> None:
        """Append one record and tally AI call outcomes for log_ai_summary."""
        kind = event.get("event")
        if kind == "ai_call":
            self._ai_stats["calls"] += 1
            if not event["accepted"]:
                self._ai_stats["illegal"] += 1
        elif kind == "ai_call_error":
            # A failed request is still a call we made.
            self._ai_stats["calls"] += 1
            self._ai_stats["errors"] += 1
        elif kind == "ai_retries_exhausted":
            self._ai_stats["turns_exhausted"] += 1
        record = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_ai_summary(self) -> None:
        """Write one `ai_stats` record: total model calls, how many failed
        (request errors + choices that didn't beat the trick) and how many
        turns gave up after all retries."""
        stats = self._ai_stats
        self.log({
            "event": "ai_stats",
            "calls": stats["calls"],
            "failed_calls": stats["errors"] + stats["illegal"],
            "request_errors": stats["errors"],
            "illegal_choices": stats["illegal"],
            "turns_exhausted": stats["turns_exhausted"],
        })
