"""Granola MCP server — wraps the granola CLI for use from sandboxed Claude sessions.

Runs natively on macOS, so the granola binary has full access to the system keychain
and the Granola API. On auth errors the server automatically attempts `granola auth login`
(which reads from the keychain non-interactively on macOS) and retries the original
command. If that re-auth takes longer than AUTH_REAUTH_TIMEOUT seconds — e.g. because a
biometrics or keychain prompt is waiting — it gives up and surfaces an error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date as Date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRANOLA_CLI = "granola"
GRANOLA_ARGS_PREFIX = []

# How long to wait for `granola auth login` before giving up. Covers Touch ID /
# keychain prompts but avoids hanging indefinitely if one is left unattended.
AUTH_REAUTH_TIMEOUT = 30

# Minimum granola-cli version known to be compatible with this server.
# Bump this when a new CLI release is required for correct behaviour.
MIN_GRANOLA_CLI_VERSION = "0.1.3"


# ---------------------------------------------------------------------------
# CLI version check
# ---------------------------------------------------------------------------

def check_cli_version() -> None:
    """Warn to stderr if the installed granola-cli is below MIN_GRANOLA_CLI_VERSION.

    Called at server startup. Logs a warning but never blocks — a version we
    can't parse is treated as compatible to avoid false positives.
    """
    rc, stdout, _ = _run_granola(["--version"])
    if rc != 0:
        return
    parts = stdout.strip().split()
    if len(parts) < 2:
        return
    try:
        actual = tuple(int(x) for x in parts[1].split("."))
        minimum = tuple(int(x) for x in MIN_GRANOLA_CLI_VERSION.split("."))
    except ValueError:
        return
    if actual < minimum:
        print(
            f"granola-mcp warning: granola-cli {parts[1]} is below the minimum "
            f"compatible version {MIN_GRANOLA_CLI_VERSION}. "
            "Upgrade with: brew upgrade tmcinerney/tap/granola-cli",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

def _run_granola(args: list[str]) -> tuple[int, str, str]:
    """Run granola-cli with given args. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        [GRANOLA_CLI] + GRANOLA_ARGS_PREFIX + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


_AUTH_ERROR_MARKERS = ("not authenticated", "auth login", "401", "unauthorized")


def _is_auth_error(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _AUTH_ERROR_MARKERS)


def _reauthenticate() -> None:
    """Run `granola auth login` with a timeout. Raises on failure or timeout."""
    try:
        result = subprocess.run(
            [GRANOLA_CLI] + GRANOLA_ARGS_PREFIX + ["auth", "login"],
            capture_output=True,
            text=True,
            timeout=AUTH_REAUTH_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Re-authentication failed: {(result.stderr or result.stdout).strip()}"
            )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Re-authentication timed out after {AUTH_REAUTH_TIMEOUT}s — "
            "a biometrics or keychain prompt may be waiting."
        )


def _run_granola_json(args: list[str]) -> Any:
    """Run granola-cli and parse JSON output, retrying once after re-auth on auth errors."""
    rc, stdout, stderr = _run_granola(args)
    if rc != 0 and _is_auth_error(stderr + stdout):
        _reauthenticate()
        rc, stdout, stderr = _run_granola(args)
    if rc != 0:
        raise RuntimeError(stderr.strip() or f"granola-cli exited with code {rc}")
    if not stdout.strip():
        raise RuntimeError("granola-cli returned empty output")
    return json.loads(stdout)


def _run_granola_text(args: list[str]) -> str:
    """Run granola-cli and return stdout, retrying once after re-auth on auth errors."""
    rc, stdout, stderr = _run_granola(args)
    if rc != 0 and _is_auth_error(stderr + stdout):
        _reauthenticate()
        rc, stdout, stderr = _run_granola(args)
    if rc != 0:
        raise RuntimeError(stderr.strip() or f"granola-cli exited with code {rc}")
    return stdout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_bound(value: str, timezone_name: Optional[str], *, is_until: bool) -> str:
    """Convert a date or RFC3339 value to a UTC CLI boundary.

    Date-only upper bounds represent the start of the following local day, so
    the CLI can apply a half-open [since, until) interval.
    """
    try:
        local_tz = ZoneInfo(timezone_name) if timezone_name else datetime.now().astimezone().tzinfo
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone_name}") from exc

    try:
        parsed_date = Date.fromisoformat(value)
    except ValueError:
        parsed_date = None

    if parsed_date:
        if is_until:
            parsed_date += timedelta(days=1)
        bound = datetime.combine(parsed_date, time.min, tzinfo=local_tz)
    else:
        try:
            bound = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Date filters must be YYYY-MM-DD or RFC3339 timestamps.") from exc
        if bound.tzinfo is None:
            raise ValueError("Timestamp filters must include a timezone offset.")

    return bound.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _add_range_args(
    args: list[str],
    prefix: str,
    since: Optional[str],
    until: Optional[str],
    timezone_name: Optional[str],
) -> None:
    normalized_since = None
    if since:
        normalized_since = _normalize_bound(since, timezone_name, is_until=False)
        args += [f"--{prefix}-since", normalized_since]
    if until:
        normalized_until = _normalize_bound(until, timezone_name, is_until=True)
        if normalized_since and normalized_since >= normalized_until:
            raise ValueError(f"{prefix}_since must be before {prefix}_until.")
        args += [f"--{prefix}-until", normalized_until]


def _build_list_args(params: "ListMeetingsInput") -> list[str]:
    """Build CLI arguments without relying on optional calendar metadata."""
    args = ["meeting", "list", "-o", "json", "--limit", str(params.limit)]
    has_created_range = any((params.created_since, params.created_until))
    has_legacy_range = any((params.since, params.until))
    if params.date and (has_created_range or has_legacy_range):
        raise ValueError("date cannot be combined with since, until, or created_* filters.")
    if has_created_range and has_legacy_range:
        raise ValueError("Use either since/until or created_since/created_until, not both.")

    if params.date:
        _add_range_args(args, "created", params.date, params.date, params.timezone)
    else:
        _add_range_args(
            args,
            "created",
            params.created_since or params.since,
            params.created_until or params.until,
            params.timezone,
        )
    _add_range_args(args, "updated", params.updated_since, params.updated_until, params.timezone)
    if params.search:
        args += ["--search", params.search]
    return args

def _format_meeting_markdown(m: dict) -> str:
    """Render a single meeting as a markdown summary block."""
    title = m.get("title") or "(Untitled)"
    mid = m.get("id", "")
    created = m.get("created_at", "")

    cal = m.get("google_calendar_event") or {}
    start = (cal.get("start") or {}).get("dateTime") or created
    end_dt = (cal.get("end") or {}).get("dateTime")

    people = m.get("people") or {}
    attendees = people.get("attendees") or []
    attendee_names = []
    for a in attendees:
        details = (a.get("details") or {}).get("person") or {}
        name = (details.get("name") or {}).get("fullName") or a.get("email", "")
        attendee_names.append(name)

    conf = (people.get("conferencing") or {}).get("type") or "unknown"

    lines = [f"### {title}", f"- **ID**: `{mid}`", f"- **Start**: {start}"]
    if end_dt:
        lines.append(f"- **End**: {end_dt}")
    lines.append(f"- **Platform**: {conf}")
    if attendee_names:
        lines.append(f"- **Attendees**: {', '.join(attendee_names)}")
    return "\n".join(lines)


def _format_transcript_markdown(utterances: list[dict]) -> str:
    """Format transcript utterances as readable markdown."""
    lines = ["# Transcript", ""]
    for u in utterances:
        speaker = "**You**" if u.get("source") == "microphone" else "**Participant**"
        text = u.get("text", "").strip()
        ts = u.get("start_timestamp", "")
        if text:
            lines.append(f"{speaker} _{ts}_: {text}")
            lines.append("")
    return "\n".join(lines)


def _handle_error(e: Exception) -> str:
    msg = str(e)
    if _is_auth_error(msg):
        return (
            "Error: Granola not authenticated and automatic re-auth failed. "
            "Run `granola auth login` in your terminal to fix this."
        )
    if "Network error" in msg:
        return "Error: Network error reaching Granola API. Check your internet connection."
    return f"Error: {msg}"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class ListMeetingsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    date: Optional[str] = Field(
        default=None,
        description="Filter meetings on a specific date. ISO format: YYYY-MM-DD (e.g. '2026-05-06'). Defaults to today.",
    )
    since: Optional[str] = Field(
        default=None,
        description="Filter meetings from this date inclusive. ISO format: YYYY-MM-DD.",
    )
    until: Optional[str] = Field(
        default=None,
        description="Filter meetings up to this date inclusive. ISO format: YYYY-MM-DD.",
    )
    created_since: Optional[str] = Field(
        default=None,
        description="Filter recordings created at or after this date or RFC3339 timestamp.",
    )
    created_until: Optional[str] = Field(
        default=None,
        description="Filter recordings created through this date or before this RFC3339 timestamp.",
    )
    updated_since: Optional[str] = Field(
        default=None,
        description="Filter documents updated at or after this date or RFC3339 timestamp.",
    )
    updated_until: Optional[str] = Field(
        default=None,
        description="Filter documents updated through this date or before this RFC3339 timestamp.",
    )
    timezone: Optional[str] = Field(
        default=None,
        description="IANA timezone for date-only filters (for example, America/Los_Angeles). Defaults to the server timezone.",
    )
    search: Optional[str] = Field(
        default=None,
        description="Search string to filter meetings by title.",
    )
    limit: int = Field(
        default=50,
        description="Maximum number of meetings to return (1-200).",
        ge=1,
        le=200,
    )
    response_format: str = Field(
        default="json",
        description="Output format: 'json' for structured data, 'markdown' for human-readable summary.",
    )


class GetMeetingNotesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    meeting_id: str = Field(
        ...,
        description="Granola meeting ID (from granola_list_meetings).",
        min_length=1,
    )


class GetTranscriptInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    meeting_id: str = Field(
        ...,
        description="Granola meeting ID (from granola_list_meetings).",
        min_length=1,
    )
    response_format: str = Field(
        default="json",
        description="Output format: 'json' for raw array, 'markdown' for readable transcript.",
    )


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def create_server() -> FastMCP:
    mcp = FastMCP(
        name="Granola",
        instructions=(
            "Access Granola meeting notes, AI-enhanced summaries, and transcripts. "
            "Use granola_list_meetings to find meetings by date, "
            "granola_get_notes to retrieve AI-enhanced notes for a meeting, "
            "and granola_get_transcript to retrieve the full transcript."
        ),
    )

    @mcp.tool(
        name="granola_list_meetings",
        annotations={
            "title": "List Granola Meetings",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def granola_list_meetings(params: ListMeetingsInput) -> str:
        """List meetings from Granola, optionally filtered by date or search query.

        Returns meeting metadata including ID, title, start time, attendees, and
        conferencing platform. Use the returned meeting IDs with granola_get_notes
        and granola_get_transcript.

        Args:
            params (ListMeetingsInput): Filter parameters:
                - date (Optional[str]): Specific date YYYY-MM-DD, defaults to today
                - since (Optional[str]): Start of date range YYYY-MM-DD
                - until (Optional[str]): End of date range YYYY-MM-DD
                - search (Optional[str]): Title search string
                - limit (int): Max results 1-200, default 50
                - response_format (str): 'json' or 'markdown'

        Returns:
            str: JSON array of meeting objects, or markdown summary list.
        """
        try:
            args = _build_list_args(params)

            meetings = _run_granola_json(args)

            if not meetings:
                return "No meetings found for the specified criteria."

            if params.response_format == "markdown":
                lines = [f"# Meetings ({len(meetings)} found)", ""]
                for m in meetings:
                    lines.append(_format_meeting_markdown(m))
                    lines.append("")
                return "\n".join(lines)

            return json.dumps(meetings, indent=2)

        except Exception as e:
            return _handle_error(e)

    @mcp.tool(
        name="granola_get_notes",
        annotations={
            "title": "Get Granola Meeting Notes",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def granola_get_notes(params: GetMeetingNotesInput) -> str:
        """Get AI-enhanced notes for a Granola meeting.

        Returns the AI-processed, structured meeting notes in markdown format.
        These notes are generated by Granola's AI and may not be immediately
        available for very recent meetings — if empty, retry later.

        Args:
            params (GetMeetingNotesInput):
                - meeting_id (str): Granola meeting ID from granola_list_meetings

        Returns:
            str: Markdown-formatted AI-enhanced meeting notes, or a warning if not ready.
        """
        try:
            stdout = _run_granola_text(
                ["meeting", "notes", params.meeting_id, "--output", "markdown"]
            )
            if not stdout.strip():
                return (
                    f"Warning: Enhanced notes not yet available for meeting {params.meeting_id}. "
                    "Granola's AI may still be processing. Try again in a few minutes."
                )
            return stdout

        except Exception as e:
            return _handle_error(e)

    @mcp.tool(
        name="granola_get_transcript",
        annotations={
            "title": "Get Granola Meeting Transcript",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def granola_get_transcript(params: GetTranscriptInput) -> str:
        """Get the full transcript for a Granola meeting.

        Returns utterances with speaker labels (You / Participant) and timestamps.
        Note: Granola desktop records two audio channels only — microphone (you)
        and system audio (all other participants) — so individual speaker
        diarization is not available.

        Args:
            params (GetTranscriptInput):
                - meeting_id (str): Granola meeting ID from granola_list_meetings
                - response_format (str): 'json' for raw array, 'markdown' for readable

        Returns:
            str: Transcript as JSON array or markdown, or error message.
        """
        try:
            utterances = _run_granola_json(
                ["meeting", "transcript", params.meeting_id, "-o", "json"]
            )

            if not utterances:
                return f"No transcript available for meeting {params.meeting_id}."

            if params.response_format == "markdown":
                return _format_transcript_markdown(utterances)

            return json.dumps(utterances, indent=2)

        except Exception as e:
            return _handle_error(e)

    return mcp
