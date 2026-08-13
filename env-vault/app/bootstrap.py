"""Bootstrap: generate ADMIN_TOKEN on first run, init DB, seed default vars."""
import os
import sys
import secrets
import hashlib
from pathlib import Path

DATA_DIR = Path("/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("DB_PATH", "/data/env-vault.db"))
TOKEN_FILE = DATA_DIR / "INITIAL_ADMIN_TOKEN"


def get_or_create_token() -> str:
    """If ADMIN_TOKEN env is set, use it. Otherwise generate a new one and persist."""
    token = os.environ.get("ADMIN_TOKEN", "").strip()
    if token:
        return token
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    # Log ONCE on first start
    print(f"[env-vault] Generated new ADMIN_TOKEN: {token}", flush=True)
    print(f"[env-vault] Token also written to {TOKEN_FILE} (chmod 600)", flush=True)
    return token


def derive_fernet_key(token: str) -> bytes:
    """Derive a Fernet key from the admin token using PBKDF2."""
    import base64
    salt = b"hermes-env-vault-v1"
    dk = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, 200_000, dklen=32)
    return base64.urlsafe_b64encode(dk)


def main():
    token = get_or_create_token()
    # Export for downstream uvicorn process
    os.environ["ADMIN_TOKEN"] = token
    os.environ["FERNET_KEY"] = derive_fernet_key(token).decode("ascii")

    # Import and init DB
    from app.main import init_db, seed_defaults
    init_db()
    seed_defaults()

    print(f"[env-vault] Bootstrap complete. DB at {DB_PATH}", flush=True)


if __name__ == "__main__":
    main()
