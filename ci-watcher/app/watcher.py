"""ci-watcher: polls Hermes upstream, triggers Coolify redeploy on new commit.

Runs as:
- HTTP health server on PORT (8203)
- Background loop that polls `git ls-remote <repo> <ref>` and triggers Coolify redeploys
"""
import asyncio
import json
import logging
import os
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ci-watcher")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = DATA_DIR / "ci-watcher.log"
LAST_SEEN_FILE = DATA_DIR / "last_seen_sha"

ENV_VAULT_URL = os.environ.get("ENV_VAULT_URL", "http://env-vault:8200")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
HERMES_GIT_REPO = os.environ.get("HERMES_GIT_REPO", "https://github.com/NousResearch/hermes-agent.git")
HERMES_GIT_REF = os.environ.get("HERMES_GIT_REF", "main")
HERMES_PLATFORM_NAME = os.environ.get("HERMES_PLATFORM_NAME", "Hermes Platform")
COOLIFY_API_KEY = os.environ.get("COOLIFY_API_KEY", "")
COOLIFY_PUBLIC_URL = os.environ.get("COOLIFY_PUBLIC_URL", "")

# In-memory state
_state = {
    "last_seen_sha": None,
    "last_poll_ts": None,
    "last_poll_result": None,
    "next_poll_at": None,
}


def _log_event(level: str, msg: str, **extra):
    rec = {"ts": int(time.time()), "level": level, "msg": msg, **extra}
    line = json.dumps(rec)
    logger.info(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


async def fetch_env_from_vault(name: str) -> Optional[str]:
    if not ADMIN_TOKEN or not ENV_VAULT_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{ENV_VAULT_URL}/api/vars/{name}",
                                 headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
            if r.status_code == 200:
                return r.json().get("value")
    except Exception as e:
        logger.warning(f"[ci-watcher] Failed to fetch {name} from env-vault: {e}")
    return None


async def init_config_from_vault():
    """Fetch HERMES_GIT_REPO, HERMES_GIT_REF, COOLIFY_API_KEY, COOLIFY_PUBLIC_URL from env-vault."""
    global HERMES_GIT_REPO, HERMES_GIT_REF, COOLIFY_API_KEY, COOLIFY_PUBLIC_URL
    for var_name, target in [
        ("HERMES_GIT_REPO", "HERMES_GIT_REPO"),
        ("HERMES_GIT_REF", "HERMES_GIT_REF"),
        ("COOLIFY_API_KEY", "COOLIFY_API_KEY"),
        ("COOLIFY_PUBLIC_URL", "COOLIFY_PUBLIC_URL"),
    ]:
        v = await fetch_env_from_vault(var_name)
        if v:
            if var_name == "HERMES_GIT_REPO": HERMES_GIT_REPO = v
            elif var_name == "HERMES_GIT_REF": HERMES_GIT_REF = v
            elif var_name == "COOLIFY_API_KEY": COOLIFY_API_KEY = v
            elif var_name == "COOLIFY_PUBLIC_URL": COOLIFY_PUBLIC_URL = v
            _log_event("info", f"Loaded {var_name} from env-vault", var=var_name, length=len(v))
        else:
            _log_event("info", f"{var_name} not in env-vault, using env", var=var_name)


def load_last_seen() -> Optional[str]:
    if LAST_SEEN_FILE.exists():
        return LAST_SEEN_FILE.read_text().strip() or None
    return None


def save_last_seen(sha: str):
    LAST_SEEN_FILE.write_text(sha)


def get_upstream_sha() -> Optional[str]:
    """Run git ls-remote and return the SHA for the given ref."""
    try:
        out = subprocess.run(
            ["git", "ls-remote", HERMES_GIT_REPO, f"refs/heads/{HERMES_GIT_REF}"],
            capture_output=True, text=True, timeout=30
        )
        if out.returncode != 0:
            _log_event("error", "git ls-remote failed", stderr=out.stderr[:200])
            return None
        line = out.stdout.strip().split("\n")[0] if out.stdout.strip() else ""
        sha = line.split()[0] if line else ""
        return sha or None
    except Exception as e:
        _log_event("error", "git ls-remote exception", error=str(e)[:200])
        return None


async def find_hermes_services_on_coolify() -> list:
    """List services on the Hermes Platform project, filtered to those depending on hermes-agent/webui."""
    if not COOLIFY_API_KEY or not COOLIFY_PUBLIC_URL:
        return []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1) Find project
            r = await client.get(f"{COOLIFY_PUBLIC_URL}/api/v1/projects",
                                 headers={"Authorization": f"Bearer {COOLIFY_API_KEY}"})
            r.raise_for_status()
            projects = r.json()
            project = next((p for p in projects if p["name"] == HERMES_PLATFORM_NAME), None)
            if not project:
                return []
            # 2) Get project env (resources list)
            r = await client.get(f"{COOLIFY_PUBLIC_URL}/api/v1/projects/{project['uuid']}/{project['uuid']}",
                                 headers={"Authorization": f"Bearer {COOLIFY_API_KEY}"})
            if r.status_code != 200:
                return []
            env = r.json()
            candidates = []
            for svc in env.get("services", []):
                raw = svc.get("docker_compose_raw", "")
                if "nousresearch/hermes-agent" in raw or "nesquena/hermes-webui" in raw or "hermes" in svc.get("name", "").lower():
                    candidates.append({"uuid": svc["uuid"], "name": svc["name"]})
            for app in env.get("applications", []):
                img = app.get("image", "")
                if "nousresearch/hermes-agent" in img or "nesquena/hermes-webui" in img:
                    candidates.append({"uuid": app["uuid"], "name": app["name"]})
            return candidates
    except Exception as e:
        _log_event("error", "find_hermes_services failed", error=str(e)[:200])
        return []


async def trigger_redeploy(service_uuid: str, service_name: str):
    if not COOLIFY_API_KEY or not COOLIFY_PUBLIC_URL:
        _log_event("warn", "Cannot trigger redeploy — no COOLIFY creds", service=service_name)
        return False
    # Try the common Coolify endpoints
    for ep in [f"/api/v1/services/{service_uuid}/deploy", f"/api/v1/applications/{service_uuid}/deploy"]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{COOLIFY_PUBLIC_URL}{ep}",
                                      headers={"Authorization": f"Bearer {COOLIFY_API_KEY}"})
                if r.status_code in (200, 201, 202):
                    _log_event("info", "Redeploy triggered", service=service_name, endpoint=ep, status=r.status_code)
                    return True
        except Exception as e:
            _log_event("error", "trigger_redeploy failed", service=service_name, endpoint=ep, error=str(e)[:200])
    return False


async def poll_once():
    """One poll cycle. Returns the new SHA, or None on error."""
    _state["last_poll_ts"] = int(time.time())
    sha = await asyncio.get_event_loop().run_in_executor(None, get_upstream_sha)
    if not sha:
        _state["last_poll_result"] = "error"
        _log_event("error", "Failed to fetch upstream SHA")
        return None
    last = _state.get("last_seen_sha")
    if last is None:
        last = load_last_seen()
        _state["last_seen_sha"] = last
    if sha != last:
        old = last
        _state["last_seen_sha"] = sha
        save_last_seen(sha)
        _log_event("info", "Upstream changed", old_sha=old, new_sha=sha)
        # Find Hermes services and trigger redeploy
        services = await find_hermes_services_on_coolify()
        if services:
            for svc in services:
                await trigger_redeploy(svc["uuid"], svc["name"])
            _log_event("info", "Triggered redeploys", count=len(services))
        else:
            _log_event("info", "No Hermes services found on Hermes Platform — nothing to redeploy")
        _state["last_poll_result"] = "changed"
    else:
        _state["last_poll_result"] = "unchanged"
        _log_event("debug", "Upstream unchanged", sha=sha)
    _state["next_poll_at"] = int(time.time()) + POLL_INTERVAL_SECONDS
    return sha


async def poll_loop():
    """Background loop that runs poll_once() every POLL_INTERVAL_SECONDS."""
    while True:
        try:
            await poll_once()
        except Exception as e:
            _log_event("error", "poll_loop exception", error=str(e)[:200])
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load config from env-vault
    await init_config_from_vault()
    # Start the poll loop in the background
    task = asyncio.create_task(poll_loop())
    yield
    task.cancel()


app = FastAPI(title="ci-watcher", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "last_seen_sha": _state.get("last_seen_sha"),
        "last_poll_ts": _state.get("last_poll_ts"),
        "last_poll_result": _state.get("last_poll_result"),
        "next_poll_in_seconds": max(0, (_state.get("next_poll_at") or 0) - int(time.time())),
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "upstream": HERMES_GIT_REPO,
        "ref": HERMES_GIT_REF,
    }


@app.get("/log")
async def log(lines: int = 50):
    if not LOG_FILE.exists():
        return {"lines": []}
    with open(LOG_FILE) as f:
        all_lines = f.readlines()
    return {"lines": all_lines[-lines:]}


@app.post("/poll")
async def poll_now():
    """Force an immediate poll (for testing)."""
    sha = await poll_once()
    return {"ok": True, "sha": sha, "last_seen_sha": _state.get("last_seen_sha")}
