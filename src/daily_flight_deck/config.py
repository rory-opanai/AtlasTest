from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SlackConfig:
    channels_exact: tuple[str, ...]
    channels_prefix: tuple[str, ...]

    @staticmethod
    def normalize_channel_name(channel_name: str) -> str:
        text = (channel_name or "").strip().lower()
        if text.startswith("#"):
            text = text[1:]
        return text

    def is_in_scope(self, channel_name: str) -> bool:
        normalized = self.normalize_channel_name(channel_name)
        exact = {self.normalize_channel_name(item) for item in self.channels_exact}
        prefixes = tuple(self.normalize_channel_name(item) for item in self.channels_prefix)
        if normalized in exact:
            return True
        return any(normalized.startswith(prefix) for prefix in prefixes)


@dataclass(frozen=True)
class EmailConfig:
    lookback_hours: int


@dataclass(frozen=True)
class CalendarConfig:
    lookahead_hours: int


@dataclass(frozen=True)
class BriefConfig:
    max_actions: int
    format: str


@dataclass(frozen=True)
class DashboardConfig:
    host: str
    port: int
    refresh_cooldown_minutes: int
    retention_days: int
    db_path: str
    snapshot_path: str


@dataclass(frozen=True)
class RuntimeConfig:
    openai_model: str
    codex_exec_model: str
    allowlisted_skills: tuple[str, ...]
    skill_execution_timeout_seconds: int
    codex_bin: str


@dataclass(frozen=True)
class FlightDeckConfig:
    timezone_source: str
    run_days: tuple[str, ...]
    run_time: str
    slack: SlackConfig
    email: EmailConfig
    calendar: CalendarConfig
    brief: BriefConfig
    dashboard: DashboardConfig
    runtime: RuntimeConfig

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "FlightDeckConfig":
        for key in ["timezone_source", "run_days", "run_time", "slack", "email", "calendar", "brief"]:
            if key not in data:
                raise ValueError(f"Missing required config key: {key}")

        slack = data["slack"]
        email = data["email"]
        calendar = data["calendar"]
        brief = data["brief"]
        dashboard = data.get("dashboard", {})
        runtime = data.get("runtime", {})
        default_allowlisted_skills = (
            "se-daily-flight-deck",
            "gh-fix-ci",
            "gh-address-comments",
            "incident-report-generator",
            "command-center-integration-audit",
            "command-center-task-ops",
        )

        return FlightDeckConfig(
            timezone_source=str(data["timezone_source"]),
            run_days=tuple(data["run_days"]),
            run_time=str(data["run_time"]),
            slack=SlackConfig(
                channels_exact=tuple(slack.get("channels_exact", [])),
                channels_prefix=tuple(slack.get("channels_prefix", [])),
            ),
            email=EmailConfig(lookback_hours=int(email["lookback_hours"])),
            calendar=CalendarConfig(lookahead_hours=int(calendar["lookahead_hours"])),
            brief=BriefConfig(max_actions=int(brief["max_actions"]), format=str(brief["format"])),
            dashboard=DashboardConfig(
                host=str(dashboard.get("host", "127.0.0.1")),
                port=int(dashboard.get("port", 2025)),
                refresh_cooldown_minutes=int(dashboard.get("refresh_cooldown_minutes", 10)),
                retention_days=int(dashboard.get("retention_days", 30)),
                db_path=str(dashboard.get("db_path", "data/flight_deck.db")),
                snapshot_path=str(dashboard.get("snapshot_path", "data/latest_snapshot.json")),
            ),
            runtime=RuntimeConfig(
                openai_model=str(runtime.get("openai_model", "gpt-4.1-mini")),
                codex_exec_model=str(runtime.get("codex_exec_model", "gpt-5")),
                allowlisted_skills=tuple(runtime.get("allowlisted_skills", default_allowlisted_skills)),
                skill_execution_timeout_seconds=int(runtime.get("skill_execution_timeout_seconds", 600)),
                codex_bin=str(runtime.get("codex_bin", "/opt/homebrew/bin/codex")),
            ),
        )


def load_config(path: str | Path) -> FlightDeckConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a mapping.")
    return FlightDeckConfig.from_dict(raw)
