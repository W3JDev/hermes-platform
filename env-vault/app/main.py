"""env-vault main app: FastAPI service for centralized env-var management.

V3: bootstrap runs in-process so FERNET_KEY is available to request handlers.
"""
import os
import sqlite3
import json
import time
import traceback
import secrets
import hashlib
import base64
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from cryptography.fernet import Fernet, InvalidToken

DB_PATH = Path(os.environ.get("DB_PATH", "/data/env-vault.db"))
STATIC_DIR = Path(__file__).parent.parent / "static"
DATA_DIR = Path("/data")
TOKEN_FILE = DATA_DIR / "INITIAL_ADMIN_TOKEN"

_conn: Optional[sqlite3.Connection] = None
_fernet: Optional[Fernet] = None
_bootstrap_done = False


def _derive_fernet_key(token: str) -> bytes:
    salt = b"hermes-env-vault-v1"
    dk = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, 200_000, dklen=32)
    return base64.urlsafe_b64encode(dk)


def _get_or_create_token() -> str:
    """Get token from env, or from /data file, or generate a new one."""
    token = os.environ.get("ADMIN_TOKEN", "").strip()
    if token:
        return token
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        if token:
            os.environ["ADMIN_TOKEN"] = token
            return token
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    os.environ["ADMIN_TOKEN"] = token
    return token


def _bootstrap():
    """Run once at app startup. Sets FERNET_KEY env var from ADMIN_TOKEN."""
    global _fernet, _bootstrap_done
    if _bootstrap_done:
        return
    _bootstrap_done = True
    # Ensure /data exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Get or create token
    token = _get_or_create_token()
    # Derive FERNET_KEY and store in env
    fkey = _derive_fernet_key(token).decode("ascii")
    os.environ["FERNET_KEY"] = fkey
    os.environ["ADMIN_TOKEN"] = token
    # Initialize the cached fernet
    _fernet = Fernet(fkey.encode("ascii"))
    # Init DB and seed
    _init_db()
    seeded = _seed_defaults()
    import sys
    print(f"[env-vault] Bootstrap complete. token_len={len(token)} seeded={seeded}", file=sys.stderr, flush=True)


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("FERNET_KEY")
        if not key:
            raise RuntimeError("FERNET_KEY not set — bootstrap did not run")
        _fernet = Fernet(key.encode("ascii"))
    return _fernet


def _init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS vars (
            name TEXT PRIMARY KEY,
            value_encrypted BLOB NOT NULL,
            scope TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            action TEXT NOT NULL,
            name TEXT NOT NULL,
            actor TEXT NOT NULL,
            detail TEXT
        );
    """)
    conn.commit()


SEED_VARS = [
    ("MINIMAX_API_KEY", "shared", ""),
    ("ANTHROPIC_API_KEY", "shared", ""),
    ("MINIMAX_TTS_MODEL", "shared", "speech-2.6-hd"),
    ("GROK_API_KEY", "shared", ""),
    ("COOLIFY_API_KEY", "shared", ""),
    ("COOLIFY_PUBLIC_URL", "shared", ""),
    ("ENV_VAULT_URL", "shared", ""),
    ("HERMES_GIT_REPO", "shared", "https://github.com/NousResearch/hermes-agent.git"),
    ("HERMES_GIT_REF", "shared", "main"),
    ("GOOGLE_CHAT_JIRAIT", "profile:jira-it", ""),
    ("JIRA_API_TOKEN", "profile:jira-it", ""),
    ("JIRA_BASE_URL", "profile:jira-it", ""),
    ("WHATSAPP_HELPLINE_TOKEN", "profile:helpline", ""),
    ("WHATSAPP_HELPLINE_PHONEID", "profile:helpline", ""),
]


def _seed_defaults() -> int:
    conn = _get_conn()
    fernet = _get_fernet()
    cur = conn.cursor()
    seeded = 0
    for name, scope, value in SEED_VARS:
        cur.execute("SELECT name FROM vars WHERE name = ?", (name,))
        if cur.fetchone():
            continue
        encrypted = fernet.encrypt(value.encode("utf-8"))
        cur.execute(
            "INSERT INTO vars (name, value_encrypted, scope, updated_at) VALUES (?, ?, ?, ?)",
            (name, encrypted, scope, int(time.time())),
        )
        _write_audit(conn, "seed", name, "system", None)
        seeded += 1
    conn.commit()
    return seeded


def _write_audit(conn, action, name, actor, detail):
    conn.execute(
        "INSERT INTO audit (ts, action, name, actor, detail) VALUES (?, ?, ?, ?, ?)",
        (int(time.time()), action, name, actor, json.dumps(detail) if detail else None),
    )


def _decrypt_value(fernet, encrypted: bytes) -> str:
    try:
        return fernet.decrypt(encrypted).decode("utf-8")
    except (InvalidToken, Exception):
        return ""


def _require_admin(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth[7:].strip()
    expected = os.environ.get("ADMIN_TOKEN", "").strip()
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap()
    yield


app = FastAPI(title="env-vault", lifespan=lifespan)


@app.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    import sys
    print(f"[env-vault] EXCEPTION: {exc}\n{tb}", file=sys.stderr, flush=True)
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "type": type(exc).__name__},
    )


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "fernet_loaded": _fernet is not None,
        "fernet_key_set": bool(os.environ.get("FERNET_KEY")),
        "admin_token_set": bool(os.environ.get("ADMIN_TOKEN")),
        "admin_token_len": len(os.environ.get("ADMIN_TOKEN", "")),
        "db_path": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
    }


@app.get("/api/debug")
def debug():
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vars")
        var_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM audit")
        audit_count = cur.fetchone()[0]
    except Exception as e:
        var_count = f"error: {e}"
        audit_count = "n/a"

    token = os.environ.get("ADMIN_TOKEN", "")
    token_preview = token[:8] + "..." if len(token) > 8 else token

    return {
        "env": {
            "ADMIN_TOKEN_set": bool(token),
            "ADMIN_TOKEN_len": len(token),
            "ADMIN_TOKEN_preview": token_preview,
            "FERNET_KEY_set": bool(os.environ.get("FERNET_KEY")),
            "DB_PATH": str(DB_PATH),
            "PORT": os.environ.get("PORT", "?"),
        },
        "fernet": {"loaded": _fernet is not None},
        "db": {"var_count": var_count, "audit_count": audit_count},
    }


@app.get("/api/vars")
def list_vars(request: Request, scope: Optional[str] = None):
    _require_admin(request)
    conn = _get_conn()
    cur = conn.cursor()
    if scope:
        cur.execute("SELECT name, scope, value_encrypted, updated_at FROM vars WHERE scope = ? ORDER BY name", (scope,))
    else:
        cur.execute("SELECT name, scope, value_encrypted, updated_at FROM vars ORDER BY name")
    rows = cur.fetchall()
    fernet = _get_fernet()
    out = []
    for r in rows:
        value = _decrypt_value(fernet, r["value_encrypted"])
        out.append({
            "name": r["name"],
            "scope": r["scope"],
            "last4": value[-4:] if value else "",
            "updated_at": r["updated_at"],
        })
    _write_audit(conn, "list", "*", "admin", None)
    conn.commit()
    return out


@app.get("/api/vars/{name}")
def get_var(name: str, request: Request):
    _require_admin(request)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name, value_encrypted, scope, updated_at FROM vars WHERE name = ?", (name,))
    row = cur.fetchone()
    if not row:
        _write_audit(conn, "get", name, "admin", {"found": False})
        conn.commit()
        raise HTTPException(status_code=404, detail=f"Variable '{name}' not found")
    fernet = _get_fernet()
    value = _decrypt_value(fernet, row["value_encrypted"])
    _write_audit(conn, "get", name, "admin", {"found": True})
    conn.commit()
    return {"name": row["name"], "value": value, "scope": row["scope"], "updated_at": row["updated_at"]}


@app.post("/api/vars")
def create_var(body: dict, request: Request):
    _require_admin(request)
    name = body.get("name", "").strip()
    value = body.get("value", "")
    scope = body.get("scope", "shared").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name'")
    if scope not in ("shared",) and not scope.startswith("profile:"):
        raise HTTPException(status_code=400, detail="Invalid scope")
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM vars WHERE name = ?", (name,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail=f"Variable '{name}' already exists")
    fernet = _get_fernet()
    encrypted = fernet.encrypt(value.encode("utf-8"))
    cur.execute(
        "INSERT INTO vars (name, value_encrypted, scope, updated_at) VALUES (?, ?, ?, ?)",
        (name, encrypted, scope, int(time.time())),
    )
    _write_audit(conn, "create", name, "admin", None)
    conn.commit()
    return {"ok": True, "name": name, "scope": scope}


@app.put("/api/vars/{name}")
def update_var(name: str, body: dict, request: Request):
    _require_admin(request)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM vars WHERE name = ?", (name,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail=f"Variable '{name}' not found")
    fernet = _get_fernet()
    if "value" in body:
        encrypted = fernet.encrypt(body["value"].encode("utf-8"))
        cur.execute("UPDATE vars SET value_encrypted = ?, updated_at = ? WHERE name = ?",
                    (encrypted, int(time.time()), name))
    if "scope" in body:
        scope = body["scope"].strip()
        if scope not in ("shared",) and not scope.startswith("profile:"):
            raise HTTPException(status_code=400, detail="Invalid scope")
        cur.execute("UPDATE vars SET scope = ?, updated_at = ? WHERE name = ?",
                    (scope, int(time.time()), name))
    _write_audit(conn, "update", name, "admin", None)
    conn.commit()
    return {"ok": True}


@app.delete("/api/vars/{name}")
def delete_var(name: str, request: Request):
    _require_admin(request)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM vars WHERE name = ?", (name,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail=f"Variable '{name}' not found")
    cur.execute("DELETE FROM vars WHERE name = ?", (name,))
    _write_audit(conn, "delete", name, "admin", None)
    conn.commit()
    return {"ok": True}


@app.get("/api/audit")
def get_audit(request: Request, limit: int = 100):
    _require_admin(request)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT ts, action, name, actor, detail FROM audit ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    return [
        {"ts": r["ts"], "action": r["action"], "name": r["name"], "actor": r["actor"], "detail": r["detail"]}
        for r in rows
    ]


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/favicon.ico")
def favicon():
    return JSONResponse(status_code=204, content=None)
