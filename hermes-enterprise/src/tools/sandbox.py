"""Sandboxed bash terminal — executes commands in isolated subprocess with timeout."""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import List, Optional


BLOCKED_PATTERNS = [
    "rm -rf /",
    ":(){ :|:& };:",
    "mkfs",
    "> /dev/sda",
    "dd if=/dev/zero",
]

BLOCKED_COMMANDS = {"sudo", "su", "passwd", "chown", "chmod"}


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class SandboxExecutor:
    """Execute shell commands in a restricted, time-limited subprocess."""

    def __init__(self, timeout: int = 30, max_output_bytes: int = 50_000):
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes

    def _check_blocked(self, command: str) -> Optional[str]:
        for pattern in BLOCKED_PATTERNS:
            if pattern in command:
                return f"Blocked: dangerous pattern '{pattern}'"
        first_word = command.strip().split()[0] if command.strip() else ""
        if first_word in BLOCKED_COMMANDS:
            return f"Blocked: command '{first_word}' is not allowed"
        return None

    async def execute(self, command: str) -> SandboxResult:
        block_reason = self._check_blocked(command)
        if block_reason:
            return SandboxResult(stdout="", stderr=block_reason, exit_code=1)

        # Build restricted environment
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "TERM": "dumb",
            "LANG": "en_US.UTF-8",
        }
        # On Windows, inherit PATH but strip sensitive vars
        if sys.platform == "win32":
            env = {k: v for k, v in os.environ.items() if k.upper() not in {
                "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "JWT_SECRET_KEY",
                "DATABASE_URL", "REDIS_URL", "OPENAI_API_KEY",
            }}

        try:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
                stdout = stdout_bytes[: self.max_output_bytes].decode("utf-8", errors="replace")
                stderr = stderr_bytes[: self.max_output_bytes].decode("utf-8", errors="replace")
                return SandboxResult(
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=proc.returncode or 0,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return SandboxResult(
                    stdout="",
                    stderr=f"Command timed out after {self.timeout}s",
                    exit_code=124,
                    timed_out=True,
                )
        except Exception as e:
            return SandboxResult(stdout="", stderr=str(e), exit_code=1)
