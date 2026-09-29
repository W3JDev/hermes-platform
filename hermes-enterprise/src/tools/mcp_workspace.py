r"""
Google Workspace MCP client — bridges the locally installed Hermes optional-mcps
for Gmail, Google Calendar, and Google Drive.

Local MCP manifests are at:
  C:\Users\W3jde\AppData\Local\hermes\hermes-agent\optional-mcps\google-calendar\
  C:\Users\W3jde\AppData\Local\hermes\hermes-agent\optional-mcps\gmail\
  C:\Users\W3jde\AppData\Local\hermes\hermes-agent\optional-mcps\google-drive\

We call them via the local Hermes API (port 9119 / Sprites gateway) which already
has Google OAuth wired up, rather than re-implementing OAuth from scratch.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from src.config import settings


SPRITES_BASE = settings.HERMES_SPRITES_BASE_URL
SPRITES_KEY  = settings.HERMES_SPRITES_API_KEY
HERMES_PORT  = settings.HERMES_LOCAL_PORT


@dataclass
class EmailSummary:
    id: str
    subject: str
    sender: str
    date: str
    snippet: str


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: str
    end: str
    attendees: List[str]


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: str


async def _hermes_tool_call(tool_name: str, args: Dict[str, Any]) -> Any:
    """
    Delegate a Google Workspace tool call to the locally running Hermes agent,
    which already has Google OAuth tokens configured.
    """
    prompt = f"Use the {tool_name} tool with these arguments: {json.dumps(args)}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SPRITES_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {SPRITES_KEY}"},
            json={
                "model": settings.HERMES_LOCAL_DEFAULT_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a Google Workspace assistant. "
                            "When asked to perform Gmail/Calendar/Drive operations, "
                            "execute them and return the structured result as JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class WorkspaceMCPClient:
    """
    Provides Gmail, Calendar, and Drive capabilities by delegating to the
    locally-running Hermes agent which has Google Workspace MCPs pre-configured.
    """

    # ── Gmail ─────────────────────────────────────────────────────────────────

    async def gmail_search(self, query: str, max_results: int = 10) -> List[EmailSummary]:
        raw = await _hermes_tool_call("gmail_search", {"query": query, "max_results": max_results})
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, list):
                return [
                    EmailSummary(
                        id=e.get("id", ""),
                        subject=e.get("subject", ""),
                        sender=e.get("from", e.get("sender", "")),
                        date=e.get("date", ""),
                        snippet=e.get("snippet", e.get("body", "")[:200]),
                    )
                    for e in data
                ]
        except Exception:
            pass
        return [EmailSummary(id="", subject="Results", sender="", date="", snippet=str(raw)[:500])]

    async def gmail_draft(self, to: str, subject: str, body: str) -> str:
        result = await _hermes_tool_call("gmail_create_draft", {"to": to, "subject": subject, "body": body})
        return str(result)

    async def gmail_send(self, to: str, subject: str, body: str) -> str:
        result = await _hermes_tool_call("gmail_send", {"to": to, "subject": subject, "body": body})
        return str(result)

    # ── Calendar ──────────────────────────────────────────────────────────────

    async def calendar_list_events(self, start_date: str, end_date: str) -> List[CalendarEvent]:
        raw = await _hermes_tool_call("google_calendar_list_events", {
            "time_min": start_date, "time_max": end_date
        })
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, list):
                return [
                    CalendarEvent(
                        id=e.get("id", ""),
                        title=e.get("summary", e.get("title", "")),
                        start=e.get("start", {}).get("dateTime", e.get("start", "")),
                        end=e.get("end", {}).get("dateTime", e.get("end", "")),
                        attendees=[a.get("email", "") for a in e.get("attendees", [])],
                    )
                    for e in data
                ]
        except Exception:
            pass
        return []

    async def calendar_create_event(
        self, title: str, start: str, end: str, attendees: Optional[List[str]] = None
    ) -> str:
        result = await _hermes_tool_call("google_calendar_create_event", {
            "summary": title, "start_time": start, "end_time": end,
            "attendees": attendees or [],
        })
        return str(result)

    # ── Drive ─────────────────────────────────────────────────────────────────

    async def drive_list_files(self, folder_id: Optional[str] = None) -> List[DriveFile]:
        args = {"folder_id": folder_id} if folder_id else {}
        raw = await _hermes_tool_call("google_drive_list_files", args)
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, list):
                return [
                    DriveFile(
                        id=f.get("id", ""),
                        name=f.get("name", ""),
                        mime_type=f.get("mimeType", ""),
                        modified_time=f.get("modifiedTime", ""),
                    )
                    for f in data
                ]
        except Exception:
            pass
        return []

    async def drive_read_file(self, file_id: str) -> str:
        result = await _hermes_tool_call("google_drive_read_file", {"file_id": file_id})
        return str(result)

    async def drive_search_files(self, query: str) -> List[DriveFile]:
        raw = await _hermes_tool_call("google_drive_search_files", {"query": query})
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, list):
                return [
                    DriveFile(
                        id=f.get("id", ""),
                        name=f.get("name", ""),
                        mime_type=f.get("mimeType", ""),
                        modified_time=f.get("modifiedTime", ""),
                    )
                    for f in data
                ]
        except Exception:
            pass
        return []


# Module-level singleton
_client: Optional[WorkspaceMCPClient] = None


def get_workspace_client() -> WorkspaceMCPClient:
    global _client
    if _client is None:
        _client = WorkspaceMCPClient()
    return _client
