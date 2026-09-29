"""
Composio integration adapter — lets team members connect external services
(GitHub, Notion, Jira, Salesforce, Linear, Slack, etc.) via OAuth and
execute actions through the Composio SDK or REST API.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from src.config import settings


COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v1"

SUPPORTED_APPS = [
    "GITHUB", "NOTION", "JIRA", "SALESFORCE", "LINEAR",
    "SLACK", "DISCORD", "GMAIL", "GCALENDAR", "GDRIVE",
    "TRELLO", "ASANA", "CLICKUP", "HUBSPOT", "ZENDESK",
]


@dataclass
class ComposioAction:
    name: str
    app: str
    description: str
    parameters: Dict[str, Any]


class ComposioAdapter:
    """
    Composio SaaS integration gateway.
    Provides per-user OAuth connection management and action execution.
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or settings.COMPOSIO_API_KEY
        self._headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _enabled(self) -> bool:
        return bool(self.api_key)

    async def get_user_connected_apps(self, tenant_id: UUID, user_id: UUID) -> List[str]:
        """List which apps this user has connected."""
        if not self._enabled():
            return []
        entity_id = f"{tenant_id}_{user_id}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{COMPOSIO_BASE_URL}/connectedAccounts",
                    headers=self._headers,
                    params={"entityId": entity_id},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    return list({item.get("appName", "").upper() for item in items if item.get("status") == "ACTIVE"})
        except Exception:
            pass
        return []

    async def get_available_actions(self, app_name: str) -> List[ComposioAction]:
        """Return available actions for an app."""
        if not self._enabled():
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{COMPOSIO_BASE_URL}/actions",
                    headers=self._headers,
                    params={"appNames": app_name.upper(), "limit": 50},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    actions = []
                    for item in data.get("items", []):
                        parameters = item.get("parameters", {})
                        if not isinstance(parameters, dict):
                            parameters = {"type": "object", "properties": {}}
                        actions.append(ComposioAction(
                            name=item.get("name", ""),
                            app=app_name.upper(),
                            description=item.get("description", ""),
                            parameters=parameters,
                        ))
                    return actions
        except Exception:
            pass
        return []

    async def execute_action(
        self,
        app_name: str,
        action_name: str,
        params: Dict[str, Any],
        tenant_id: UUID,
        user_id: UUID,
    ) -> Dict[str, Any]:
        """Execute an action using the user's stored credentials."""
        if not self._enabled():
            return {"error": "Composio not configured. Set COMPOSIO_API_KEY in .env"}

        entity_id = f"{tenant_id}_{user_id}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{COMPOSIO_BASE_URL}/actions/{action_name}/execute",
                    headers=self._headers,
                    json={
                        "entityId": entity_id,
                        "appName": app_name.upper(),
                        "input": params,
                    },
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Composio API error {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    async def get_connection_url(
        self, app_name: str, tenant_id: UUID, user_id: UUID
    ) -> str:
        """Generate an OAuth connect URL so the user can authenticate a new app."""
        if not self._enabled():
            return "Composio not configured — set COMPOSIO_API_KEY"

        entity_id = f"{tenant_id}_{user_id}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{COMPOSIO_BASE_URL}/connectedAccounts",
                    headers=self._headers,
                    json={
                        "appName": app_name.upper(),
                        "entityId": entity_id,
                        "redirectUri": f"{settings.BASE_URL}/tools/composio/callback",
                    },
                )
                data = resp.json()
                return data.get("redirectUrl", data.get("connectionUrl", f"https://app.composio.dev/apps/{app_name.lower()}"))
        except Exception as e:
            return f"Error generating connection URL: {e}"

    async def get_oauth_url(self, tenant_id: UUID, user_id: UUID, app_name: str) -> str:
        return await self.get_connection_url(app_name=app_name, tenant_id=tenant_id, user_id=user_id)

    def get_supported_apps(self) -> List[str]:
        return SUPPORTED_APPS


# Module-level singleton
_adapter: Optional[ComposioAdapter] = None


def get_composio() -> ComposioAdapter:
    global _adapter
    if _adapter is None:
        _adapter = ComposioAdapter()
    return _adapter
