"""
Traversal-Safe Private File Sandbox Storage Manager.
Enforces strict filesystem containment within /var/hermes/data/tenants/{tenant_id}/users/{user_id}/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import mimetypes
import os
from pathlib import Path
import re
from typing import AsyncIterator, Optional, Union
from uuid import UUID, uuid4

import aiofiles
import aiofiles.os

import urllib.parse

from src.config import settings


class PathTraversalError(Exception):
    """Raised when an operation attempts to access or resolve a path outside the designated sandbox."""
    pass


def resolve_user_file_path(
    tenant_id: UUID,
    user_id: UUID,
    relative_path: str,
    base_data_root: Union[str, Path] = "/var/hermes/data",
    allow_symlinks: bool = False,
) -> Path:
    """
    Resolves a relative file path within the user's isolated private sandbox directory.
    
    Guarantees:
    - Path cannot escape base_data_root/tenants/{tenant_id}/users/{user_id}/.
    - Absolute paths, drive anchors, UNC paths, and null bytes are rejected immediately.
    - Resolves all '.' and '..' segments and canonicalizes symlinks.
    - Raises PathTraversalError on any violation.
    """
    if not relative_path or not relative_path.strip():
        raise PathTraversalError("Empty file path provided.")

    # 1. Reject null byte injection
    if "\0" in relative_path:
        raise PathTraversalError("Null byte detected in path.")

    # 2. URL decode before evaluation (e.g. ..%2f..%2f)
    decoded = urllib.parse.unquote(relative_path)
    if "\0" in decoded:
        raise PathTraversalError("Null byte detected in decoded path.")

    # 3. Normalize path separators (handles Windows backslashes)
    normalized = decoded.replace("\\", "/")

    # 4. Reject multi-dot evasion sequences (e.g. ....//)
    if re.search(r"\.{3,}", normalized):
        raise PathTraversalError(f"Multiple consecutive dots detected: {relative_path}")

    # 5. Reject absolute paths, UNC shares, and Windows drive roots
    p = Path(normalized)
    if p.is_absolute() or p.anchor or normalized.startswith("/") or bool(re.match(r"^[a-zA-Z]:", normalized)):
        raise PathTraversalError(f"Absolute or anchored paths are forbidden: {relative_path}")

    # 6. Resolve sandbox root directory
    sandbox_root = (
        Path(base_data_root) / "tenants" / str(tenant_id) / "users" / str(user_id)
    ).resolve()

    # 7. Resolve candidate target path
    target = (sandbox_root / p).resolve()

    # 8. Verify target is strictly within sandbox_root
    try:
        target.relative_to(sandbox_root)
    except ValueError:
        raise PathTraversalError(
            f"Path traversal detected: '{relative_path}' resolves outside sandbox '{sandbox_root}'"
        )

    # 9. Disallow symlink hops unless explicitly permitted
    if not allow_symlinks:
        check_node = sandbox_root / p
        curr = check_node
        while curr != sandbox_root and curr != curr.parent:
            if curr.is_symlink():
                raise PathTraversalError(f"Symlink traversal forbidden: '{curr}'")
            curr = curr.parent

    return target


@dataclass(frozen=True)
class UserFileInfo:
    """Metadata container for saved user files."""
    file_id: UUID
    tenant_id: UUID
    user_id: UUID
    filename: str
    sanitized_filename: str
    physical_path: Path
    file_size_bytes: int
    sha256_checksum: str
    mime_type: str
    created_at: datetime


class FileSandboxManager:
    """Manages traversal-safe physical storage within base_data_root/tenants/{tid}/users/{uid}/."""

    def __init__(
        self,
        base_data_root: Optional[Union[str, Path]] = None,
        max_file_size_bytes: Optional[int] = None,
    ):
        self.base_data_root = Path(base_data_root or settings.DATA_ROOT_DIR)
        self.max_file_size_bytes = max_file_size_bytes or settings.MAX_FILE_SIZE_BYTES

    def get_user_root(self, tenant_id: UUID, user_id: UUID) -> Path:
        """Returns the canonical root directory for a given tenant user, creating if needed."""
        root = (self.base_data_root / "tenants" / str(tenant_id) / "users" / str(user_id)).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def resolve_path(self, tenant_id: UUID, user_id: UUID, relative_path: str) -> Path:
        """Resolves and validates a relative path inside the user sandbox."""
        return resolve_user_file_path(
            tenant_id=tenant_id,
            user_id=user_id,
            relative_path=relative_path,
            base_data_root=self.base_data_root,
        )

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitizes an uploaded filename to prevent shell/path injection."""
        base = os.path.basename(filename)
        cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
        cleaned = cleaned.lstrip(".")
        return cleaned[:200] or "unnamed_file"

    async def save_user_file(
        self,
        tenant_id: UUID,
        user_id: UUID,
        filename: str,
        content_stream: AsyncIterator[bytes],
        file_id: Optional[UUID] = None,
    ) -> UserFileInfo:
        """
        Streams content to an isolated file using an atomic write pattern:
        1. Write to temporary file (.tmp.<uuid>).
        2. Verify size and compute SHA-256 on the fly.
        3. Atomically rename to final physical target.
        """
        actual_file_id = file_id or uuid4()
        sanitized = self.sanitize_filename(filename)
        user_files_dir = self.get_user_root(tenant_id, user_id) / "files"
        user_files_dir.mkdir(parents=True, exist_ok=True)

        target_name = f"{actual_file_id}_{sanitized}"
        target_path = self.resolve_path(tenant_id, user_id, f"files/{target_name}")
        temp_path = self.resolve_path(tenant_id, user_id, f"files/.tmp.{actual_file_id}")

        hasher = hashlib.sha256()
        bytes_written = 0

        try:
            async with aiofiles.open(temp_path, "wb") as f:
                async for chunk in content_stream:
                    bytes_written += len(chunk)
                    if bytes_written > self.max_file_size_bytes:
                        raise ValueError(
                            f"File exceeds maximum allowed size of {self.max_file_size_bytes} bytes."
                        )
                    hasher.update(chunk)
                    await f.write(chunk)
                await f.flush()

            await aiofiles.os.replace(temp_path, target_path)

        except Exception:
            if await aiofiles.os.path.exists(temp_path):
                await aiofiles.os.remove(temp_path)
            raise

        guessed_mime, _ = mimetypes.guess_type(sanitized)
        mime_type = guessed_mime or "application/octet-stream"

        return UserFileInfo(
            file_id=actual_file_id,
            tenant_id=tenant_id,
            user_id=user_id,
            filename=filename,
            sanitized_filename=sanitized,
            physical_path=target_path,
            file_size_bytes=bytes_written,
            sha256_checksum=hasher.hexdigest(),
            mime_type=mime_type,
            created_at=datetime.now(timezone.utc),
        )

    async def read_user_file_stream(
        self,
        tenant_id: UUID,
        user_id: UUID,
        relative_path: str,
        chunk_size: int = 65536,
    ) -> AsyncIterator[bytes]:
        """Streams file bytes safely from the user's sandbox."""
        resolved = self.resolve_path(tenant_id, user_id, relative_path)
        if not await aiofiles.os.path.exists(resolved):
            raise FileNotFoundError(f"File not found: {relative_path}")

        async with aiofiles.open(resolved, "rb") as f:
            while chunk := await f.read(chunk_size):
                yield chunk

    async def delete_user_file(
        self,
        tenant_id: UUID,
        user_id: UUID,
        relative_path: str,
    ) -> bool:
        """Safely deletes a file within the user sandbox."""
        resolved = self.resolve_path(tenant_id, user_id, relative_path)
        if await aiofiles.os.path.exists(resolved):
            await aiofiles.os.remove(resolved)
            return True
        return False
