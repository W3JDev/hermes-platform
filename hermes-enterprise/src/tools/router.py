"""Tools router — exposes tool management and Composio connect endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from uuid import UUID

from src.auth.rbac import AuthenticatedUser, get_current_user
from src.tools.composio import get_composio
from src.tools.registry import get_registry
from src.tools.skills import SkillsManager

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolListResponse(BaseModel):
    tools: list
    count: int


class ComposioConnectResponse(BaseModel):
    app: str
    connect_url: str


class ComposioAppsResponse(BaseModel):
    connected: list
    supported: list


@router.get("/list", response_model=ToolListResponse)
async def list_tools(current_user: AuthenticatedUser = Depends(get_current_user)):
    reg = get_registry()
    tools = reg.list_tools()
    return ToolListResponse(tools=tools, count=len(tools))


@router.get("/skills")
async def list_skills(current_user: AuthenticatedUser = Depends(get_current_user)):
    mgr = SkillsManager(tenant_id=current_user.tenant_id)
    skills = await mgr.skill_list()
    return {"skills": skills, "count": len(skills)}


@router.get("/skills/{name}")
async def get_skill(name: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    mgr = SkillsManager(tenant_id=current_user.tenant_id)
    content = await mgr.skill_get(name)
    return {"name": name, "content": content}


@router.get("/composio/apps", response_model=ComposioAppsResponse)
async def composio_apps(current_user: AuthenticatedUser = Depends(get_current_user)):
    comp = get_composio()
    connected = await comp.get_user_connected_apps(current_user.tenant_id, current_user.user_id)
    return ComposioAppsResponse(connected=connected, supported=comp.get_supported_apps())


@router.post("/composio/connect/{app_name}", response_model=ComposioConnectResponse)
async def composio_connect(
    app_name: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    comp = get_composio()
    url = await comp.get_connection_url(app_name.upper(), current_user.tenant_id, current_user.user_id)
    return ComposioConnectResponse(app=app_name.upper(), connect_url=url)
