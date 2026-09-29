r"""
Skills Manager — reads agentskills.io-standard skills from local Hermes installation
AND from the per-tenant cloud skills directory.

Local Hermes skills path: C:\Users\W3jde\AppData\Local\hermes\hermes-agent\skills\
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import aiofiles

from src.config import settings


HERMES_LOCAL_SKILLS = Path(r"C:\Users\W3jde\AppData\Local\hermes\hermes-agent\skills")


@dataclass
class SkillSummary:
    name: str
    description: str
    source: str  # 'local_hermes' | 'tenant'
    path: str


class SkillsManager:
    """Read, create, update, and delete agent skills from Hermes local + tenant dirs."""

    def __init__(self, tenant_id: Optional[UUID] = None):
        self.tenant_id = tenant_id
        self._tenant_skills_dir = (
            Path(settings.DATA_ROOT_DIR) / "tenants" / str(tenant_id) / "skills"
            if tenant_id
            else None
        )

    async def skill_list(self) -> List[Dict[str, Any]]:
        skills = []

        # Local Hermes skills (from installed instance)
        if HERMES_LOCAL_SKILLS.exists():
            for skill_dir in HERMES_LOCAL_SKILLS.iterdir():
                if skill_dir.is_dir():
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        description = await self._extract_description(skill_md)
                        skills.append({
                            "name": skill_dir.name,
                            "description": description,
                            "source": "local_hermes",
                            "path": str(skill_md),
                        })

        # Tenant-specific skills
        if self._tenant_skills_dir and self._tenant_skills_dir.exists():
            for skill_file in self._tenant_skills_dir.glob("*.md"):
                description = await self._extract_description(skill_file)
                skills.append({
                    "name": skill_file.stem,
                    "description": description,
                    "source": "tenant",
                    "path": str(skill_file),
                })

        return skills

    async def skill_get(self, name: str) -> str:
        # Check tenant skills first
        if self._tenant_skills_dir:
            tenant_file = self._tenant_skills_dir / f"{name}.md"
            if tenant_file.exists():
                async with aiofiles.open(tenant_file, "r", encoding="utf-8") as f:
                    return await f.read()

        # Check local Hermes skills
        local_skill = HERMES_LOCAL_SKILLS / name / "SKILL.md"
        if local_skill.exists():
            async with aiofiles.open(local_skill, "r", encoding="utf-8") as f:
                return await f.read()

        raise FileNotFoundError(f"Skill '{name}' not found")

    async def skill_create(self, name: str, content: str) -> None:
        if not self._tenant_skills_dir:
            raise ValueError("tenant_id required to create skills")
        self._tenant_skills_dir.mkdir(parents=True, exist_ok=True)
        path = self._tenant_skills_dir / f"{name}.md"
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)

    async def skill_update(self, name: str, content: str) -> None:
        await self.skill_create(name, content)  # overwrite

    async def skill_delete(self, name: str) -> None:
        if not self._tenant_skills_dir:
            raise ValueError("tenant_id required to delete skills")
        path = self._tenant_skills_dir / f"{name}.md"
        if path.exists():
            path.unlink()
        else:
            raise FileNotFoundError(f"Tenant skill '{name}' not found")

    @staticmethod
    async def _extract_description(path: Path) -> str:
        """Extract first non-empty line after the H1 title as description."""
        try:
            async with aiofiles.open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = await f.read()
            lines = content.split("\n")
            found_title = False
            for line in lines:
                line = line.strip()
                if line.startswith("# "):
                    found_title = True
                    continue
                if found_title and line and not line.startswith("#"):
                    return line[:120]
            # Fallback: first non-empty line
            return next((l.strip()[:120] for l in lines if l.strip()), "No description")
        except Exception:
            return "No description"
