"""Presenter logic for viewing structured job logs in the admin UI."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .helpers import build_layout_context


@dataclass(slots=True)
class LogFileSummary:
    """Container for metadata and entries of a single log file."""

    name: str
    modified_display: str
    entries: List[Dict[str, Any]]


@dataclass(slots=True)
class LogsPresenter:
    """Load structured log files from disk and present them in the UI."""

    templates: Jinja2Templates
    log_directory: Path = field(default_factory=lambda: Path("logs") / "jobs")
    api_log_path: Path = field(default_factory=lambda: Path("logs") / "api_requests.log")
    max_files: int = 10
    max_entries_per_file: int = 50
    max_api_entries: int = 200

    def render(self, request: Request, user: Any, db: Session) -> Any:
        log_files = self._collect_log_files()
        api_entries = self._load_api_entries()
        context: Dict[str, Any] = build_layout_context(
            request=request,
            user=user,
            db=db,
            active_page="logs",
            log_files=log_files,
            api_entries=api_entries,
        )
        return self.templates.TemplateResponse("logs.html", context)

    def _collect_log_files(self) -> List[LogFileSummary]:
        if not self.log_directory.exists():
            return []

        def sort_key(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        summaries: List[LogFileSummary] = []
        for path in sorted(
            self.log_directory.glob("*.log"), key=sort_key, reverse=True
        )[: self.max_files]:
            entries = self._load_entries(path)
            modified_display = self._format_timestamp(path)
            summaries.append(
                LogFileSummary(
                    name=path.name,
                    modified_display=modified_display,
                    entries=entries,
                )
            )
        return summaries

    def _load_entries(self, path: Path) -> List[Dict[str, Any]]:
        lines: deque[str] = deque(maxlen=self.max_entries_per_file)
        try:
            with path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    lines.append(line)
        except OSError as exc:
            return [
                {
                    "level": "ERROR",
                    "badge_class": "danger",
                    "timestamp": "",
                    "message": f"خطا در خواندن فایل لاگ: {exc}",
                    "details": "",
                }
            ]

        entries: List[Dict[str, Any]] = []
        for line in reversed(list(lines)):
            entry = self.parse_log_line(line)
            entries.append(entry)
        return entries

    def parse_log_line(self, line: str) -> Dict[str, Any]:
        """Parse a raw JSON log line into a dictionary for rendering."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return {
                "level": "INFO",
                "badge_class": "info",
                "timestamp": "",
                "message": line,
                "details": "",
            }

        level = str(data.get("level", "INFO")).upper()
        badge_class = self._level_to_badge(level)
        timestamp = str(data.get("timestamp", ""))
        message = str(data.get("message", ""))
        details_dict = {
            key: value
            for key, value in data.items()
            if key not in {"timestamp", "level", "message"}
        }
        details = json.dumps(details_dict, ensure_ascii=False, indent=2) if details_dict else ""

        return {
            "level": level,
            "badge_class": badge_class,
            "timestamp": timestamp,
            "message": message,
            "details": details,
        }

    def _load_api_entries(self) -> List[Dict[str, Any]]:
        path = self.api_log_path
        if not path.exists():
            return []

        lines: deque[str] = deque(maxlen=self.max_api_entries)
        try:
            with path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    lines.append(line)
        except OSError as exc:
            return [
                {
                    "level": "ERROR",
                    "badge_class": "danger",
                    "timestamp": "",
                    "message": "خطا در خواندن لاگ درخواست‌های API",
                    "details": str(exc),
                }
            ]

        entries: List[Dict[str, Any]] = []
        for line in reversed(list(lines)):
            entry = self._parse_api_log_line(line)
            entries.append(entry)
        return entries

    def _parse_api_log_line(self, line: str) -> Dict[str, Any]:
        parts = line.split("\t", 3)
        if len(parts) < 4:
            return {
                "level": "INFO",
                "badge_class": "info",
                "timestamp": "",
                "message": line,
                "details": "",
            }

        timestamp, level, logger_name, message = parts
        level = level.upper()
        badge_class = self._level_to_badge(level)
        event, details_dict = self._parse_structured_message(message)
        details_dict["logger"] = logger_name
        details = json.dumps(details_dict, ensure_ascii=False, indent=2) if details_dict else ""

        return {
            "level": level,
            "badge_class": badge_class,
            "timestamp": timestamp,
            "message": event,
            "details": details,
        }

    @staticmethod
    def _parse_structured_message(message: str) -> Tuple[str, Dict[str, Any]]:
        parts = message.split("\t")
        if not parts:
            return message, {}

        event = parts[0]
        details: Dict[str, Any] = {}
        extras: List[str] = []
        for token in parts[1:]:
            if "=" in token:
                key, value = token.split("=", 1)
                details[key] = value
            elif token:
                extras.append(token)

        if extras:
            details["extra"] = ", ".join(extras)

        return event, details

    @staticmethod
    def _level_to_badge(level: str) -> str:
        mapping = {
            "DEBUG": "secondary",
            "INFO": "info",
            "WARNING": "warning",
            "ERROR": "danger",
            "CRITICAL": "danger",
        }
        return mapping.get(level, "secondary")

    @staticmethod
    def _format_timestamp(path: Path) -> str:
        try:
            modified_ts = path.stat().st_mtime
        except OSError:
            return ""
        modified_dt = datetime.fromtimestamp(modified_ts)
        return modified_dt.strftime("%Y-%m-%d %H:%M:%S")
