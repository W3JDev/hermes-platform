"""Unified tool registry for all Hermes tool providers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional
from uuid import UUID


@dataclass
class ToolDefinitionReg:
    name: str
    description: str
    parameters: Dict[str, Any]
    provider: str = "core"


@dataclass
class ToolExecutionResult:
    tool_call_id: str
    success: bool
    output: Any
    error: Optional[str] = None


class ToolRegistry:
    """Central registry: aggregates tools from all providers, dispatches execution."""

    def __init__(self):
        self._tools: Dict[str, ToolDefinitionReg] = {}
        self._handlers: Dict[str, Callable] = {}

    def register(self, definition: ToolDefinitionReg, handler: Callable) -> None:
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler

    def get_all_definitions(self) -> List[Dict[str, Any]]:
        """Return tool schemas in OpenAI function-calling format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tenant_id: UUID,
        user_id: UUID,
        tool_call_id: str = "",
    ) -> ToolExecutionResult:
        handler = self._handlers.get(tool_name)
        if not handler:
            return ToolExecutionResult(
                tool_call_id=tool_call_id,
                success=False,
                output=None,
                error=f"Unknown tool: {tool_name}",
            )
        try:
            result = await handler(**arguments, tenant_id=tenant_id, user_id=user_id)
            return ToolExecutionResult(tool_call_id=tool_call_id, success=True, output=result)
        except Exception as e:
            return ToolExecutionResult(
                tool_call_id=tool_call_id, success=False, output=None, error=str(e)
            )

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())


# Module-level singleton
_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _bootstrap_registry(_registry)
    return _registry


def _bootstrap_registry(registry: ToolRegistry) -> None:
    """Register all built-in tools on startup."""
    # Sandbox terminal
    from src.tools.sandbox import SandboxExecutor
    sandbox = SandboxExecutor()

    async def _bash(command: str, **_) -> str:
        result = await sandbox.execute(command)
        return f"exit={result.exit_code}\n{result.stdout}\n{result.stderr}".strip()

    registry.register(
        ToolDefinitionReg(
            name="bash",
            description="Execute a bash/shell command in a sandboxed environment. Returns stdout, stderr, and exit code.",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Shell command to execute"}},
                "required": ["command"],
            },
            provider="sandbox",
        ),
        _bash,
    )

    # Skills manager
    async def _list_skills(**_) -> str:
        from src.tools.skills import SkillsManager
        mgr = SkillsManager()
        skills = await mgr.skill_list()
        return "\n".join(f"- {s['name']}: {s['description']}" for s in skills) or "No skills found."

    registry.register(
        ToolDefinitionReg(
            name="list_skills",
            description="List all available agent skills.",
            parameters={"type": "object", "properties": {}},
            provider="skills",
        ),
        _list_skills,
    )

    # Browser
    async def _browse(url: str, **_) -> str:
        from src.tools.browser import BrowserTool
        async with BrowserTool() as browser:
            await browser.navigate(url)
            return await browser.get_text()

    registry.register(
        ToolDefinitionReg(
            name="browse",
            description="Navigate to a URL and return the visible text content of the page.",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL to visit"}},
                "required": ["url"],
            },
            provider="browser",
        ),
        _browse,
    )

    # Hermes local skill execution — delegate to locally running Hermes
    async def _hermes_task(task: str, **_) -> str:
        """Send a task to the locally running Hermes agent and return its response."""
        import httpx
        from src.config import settings
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{settings.HERMES_SPRITES_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.HERMES_SPRITES_API_KEY}"},
                    json={
                        "model": settings.HERMES_LOCAL_DEFAULT_MODEL,
                        "messages": [{"role": "user", "content": task}],
                        "max_tokens": 2048,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Hermes local error: {e}"

    registry.register(
        ToolDefinitionReg(
            name="hermes_task",
            description="Delegate a complex task to the locally running Hermes AI agent (has access to Claude, GPT-5.5, MiniMax).",
            parameters={
                "type": "object",
                "properties": {"task": {"type": "string", "description": "The task to delegate to Hermes"}},
                "required": ["task"],
            },
            provider="hermes_local",
        ),
        _hermes_task,
    )

    # ── R4 Native Coding Agents ───────────────────────────────────────────────
    from src.tools.coding_agents import claude_harness, agy_orchestrator, persistent_terminal

    async def _claude_code(prompt: str, workspace: Optional[str] = None, dangerously_skip_permissions: bool = False, **_) -> str:
        res = await claude_harness.run_claude_command(prompt, workspace=workspace, dangerously_skip_permissions=dangerously_skip_permissions)
        return f"exit={res.exit_code}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}".strip()

    registry.register(
        ToolDefinitionReg(
            name="claude_code",
            description="Execute Claude Code CLI commands with controlled workspace boundaries, timeout limits, and stdout/stderr capture.",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Prompt or instruction for Claude Code CLI"},
                    "workspace": {"type": "string", "description": "Target workspace directory path"},
                    "dangerously_skip_permissions": {"type": "boolean", "description": "Bypass interactive permission prompts"},
                },
                "required": ["prompt"],
            },
            provider="coding_agents",
        ),
        _claude_code,
    )

    async def _agy_orchestrate(task: str, agent_type: str = "implementer", **_) -> str:
        res = await agy_orchestrator.orchestrate_task(task, agent_type=agent_type)
        import json
        return json.dumps(res, indent=2)

    registry.register(
        ToolDefinitionReg(
            name="agy_orchestrate",
            description="Native orchestration hooks for running multi-agent tasks using Google Antigravity SDK (AGY).",
            parameters={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Multi-agent task description"},
                    "agent_type": {"type": "string", "description": "Specialist agent role or archetype"},
                },
                "required": ["task"],
            },
            provider="coding_agents",
        ),
        _agy_orchestrate,
    )

    async def _powershell_session(command: str, session_id: Optional[str] = None, **_) -> str:
        res = await persistent_terminal.execute_command(command, session_id=session_id, shell_type="powershell")
        return f"session={res['session_id']}\ncwd={res['cwd']}\nexit={res['exit_code']}\n{res['stdout']}\n{res['stderr']}".strip()

    registry.register(
        ToolDefinitionReg(
            name="powershell_session",
            description="Stateful PowerShell terminal execution preserving working directory across commands.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell command to execute"},
                    "session_id": {"type": "string", "description": "Unique session ID to maintain persistent working directory"},
                },
                "required": ["command"],
            },
            provider="coding_agents",
        ),
        _powershell_session,
    )

    async def _bash_session(command: str, session_id: Optional[str] = None, **_) -> str:
        res = await persistent_terminal.execute_command(command, session_id=session_id, shell_type="bash")
        return f"session={res['session_id']}\ncwd={res['cwd']}\nexit={res['exit_code']}\n{res['stdout']}\n{res['stderr']}".strip()

    registry.register(
        ToolDefinitionReg(
            name="bash_session",
            description="Stateful bash terminal execution preserving working directory across commands.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Bash command to execute"},
                    "session_id": {"type": "string", "description": "Unique session ID to maintain persistent working directory"},
                },
                "required": ["command"],
            },
            provider="coding_agents",
        ),
        _bash_session,
    )

    # ── R5 Google Workspace MCP Tools ─────────────────────────────────────────
    from src.tools.mcp_workspace import get_workspace_client
    ws_client = get_workspace_client()

    async def _gmail_search(query: str, max_results: int = 10, **_) -> str:
        res = await ws_client.gmail_search(query, max_results=max_results)
        import json
        return json.dumps([{"id": e.id, "subject": e.subject, "sender": e.sender, "date": e.date, "snippet": e.snippet} for e in res], indent=2)

    registry.register(
        ToolDefinitionReg(
            name="gmail_search",
            description="Search user Gmail messages matching search query via Google Workspace MCP.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query syntax"},
                    "max_results": {"type": "integer", "description": "Max results to return (default 10)"},
                },
                "required": ["query"],
            },
            provider="google_workspace_mcp",
        ),
        _gmail_search,
    )

    async def _gmail_send(to: str, subject: str, body: str, **_) -> str:
        return await ws_client.gmail_send(to=to, subject=subject, body=body)

    registry.register(
        ToolDefinitionReg(
            name="gmail_send",
            description="Send an email via Google Workspace MCP Gmail integration.",
            parameters={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body": {"type": "string", "description": "Plain text email body"},
                },
                "required": ["to", "subject", "body"],
            },
            provider="google_workspace_mcp",
        ),
        _gmail_send,
    )

    async def _calendar_create_event(title: str, start: str, end: str, attendees: Optional[List[str]] = None, **_) -> str:
        return await ws_client.calendar_create_event(title=title, start=start, end=end, attendees=attendees)

    registry.register(
        ToolDefinitionReg(
            name="calendar_create_event",
            description="Create a calendar meeting event via Google Workspace MCP Calendar integration.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Meeting title / summary"},
                    "start": {"type": "string", "description": "ISO-8601 start datetime"},
                    "end": {"type": "string", "description": "ISO-8601 end datetime"},
                    "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails"},
                },
                "required": ["title", "start", "end"],
            },
            provider="google_workspace_mcp",
        ),
        _calendar_create_event,
    )

    async def _drive_search_files(query: str, **_) -> str:
        res = await ws_client.drive_search_files(query=query)
        import json
        return json.dumps([{"id": f.id, "name": f.name, "mime_type": f.mime_type} for f in res], indent=2)

    registry.register(
        ToolDefinitionReg(
            name="drive_search_files",
            description="Search files in Google Drive by name or keyword via Google Workspace MCP.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Filename or keyword query"},
                },
                "required": ["query"],
            },
            provider="google_workspace_mcp",
        ),
        _drive_search_files,
    )

    # ── Composio SaaS Action Execution ────────────────────────────────────────
    from src.tools.composio import get_composio
    comp_adapter = get_composio()

    async def _composio_action(action: str, params: Optional[Dict[str, Any]] = None, **_) -> str:
        import json
        app = action.split("_")[0].upper()
        dummy_tenant = uuid.UUID("11111111-1111-1111-1111-111111111111")
        dummy_user = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        res = await comp_adapter.execute_action(
            app_name=app, action_name=action, params=params or {}, tenant_id=dummy_tenant, user_id=dummy_user
        )
        return json.dumps(res, indent=2)

    registry.register(
        ToolDefinitionReg(
            name="composio_action",
            description="Execute SaaS actions (GitHub, Jira, Notion, Linear, Slack) via Composio OAuth integrations.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Composio action name (e.g. JIRA_CREATE_ISSUE)"},
                    "params": {"type": "object", "description": "Input parameters for action execution"},
                },
                "required": ["action"],
            },
            provider="composio",
        ),
        _composio_action,
    )
