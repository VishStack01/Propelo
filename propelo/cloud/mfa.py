"""Two-step sign-in with an authenticator app (TOTP, RFC 6238: 30-second steps, 6 digits, SHA-1).

- Setup stores an encrypted secret; it only takes effect once the person enters a working code.
- Each code works once (the last accepted time step is remembered), within one step either side.
- Ten one-time recovery codes are shown once and stored as hashes.
- Sign-in with a password (or LinkedIn) then needs a code: the first step returns a short-lived signed
  ticket instead of a session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

from . import plans
from .db import Conn, now_iso

STEP = 30
DIGITS = 6
TICKET_SECONDS = 300


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code_at(secret: str, step: int) -> str:
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(n).zfill(DIGITS)


def check(secret: str, code: str, last_step: int = 0, now: float | None = None) -> int:
    """The time step the code belongs to (accepting one step either side), or 0. A step at or before
    `last_step` is refused, so a code can't be replayed."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != DIGITS:
        return 0
    cur = int((now if now is not None else time.time()) // STEP)
    for step in (cur - 1, cur, cur + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return 0


def uri(secret: str, email: str, issuer: str = "Propelo") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"


def _hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def recovery_codes(n: int = 10) -> list[str]:
    return [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(n)]


def seal(cfg, secret: str) -> str:
    return plans._fernet(cfg).encrypt(secret.encode()).decode()


def unseal(cfg, sealed: str) -> str:
    return plans._fernet(cfg).decrypt(sealed.encode()).decode()


def enabled(user: dict) -> bool:
    return bool(user.get("mfa_enabled_at"))


def begin(c: Conn, cfg, user: dict) -> dict:
    """Start setup: a new secret, not yet active."""
    secret = new_secret()
    c.execute("UPDATE users SET mfa_secret = ?, mfa_enabled_at = NULL, mfa_last_step = 0 WHERE id = ?", (seal(cfg, secret), user["id"]))
    return {"secret": secret, "uri": uri(secret, user["email"])}


def confirm(c: Conn, cfg, user: dict, code: str) -> list[str] | None:
    """Turn it on with a working code. Returns the recovery codes (shown once), or None for a wrong code."""
    if not user.get("mfa_secret"):
        return None
    step = check(unseal(cfg, user["mfa_secret"]), code)
    if not step:
        return None
    codes = recovery_codes()
    c.execute("UPDATE users SET mfa_enabled_at = ?, mfa_last_step = ?, mfa_recovery = ? WHERE id = ?",
              (now_iso(), step, json.dumps([_hash(x) for x in codes]), user["id"]))
    return codes


def verify(c: Conn, cfg, user: dict, code: str) -> bool:
    """A code from the app, or an unused recovery code (which is then spent)."""
    if not enabled(user):
        return True
    step = check(unseal(cfg, user["mfa_secret"]), code, int(user.get("mfa_last_step") or 0))
    if step:
        c.execute("UPDATE users SET mfa_last_step = ? WHERE id = ?", (step, user["id"]))
        return True
    left = json.loads(user.get("mfa_recovery") or "[]")
    h = _hash(code)
    if h in left:
        left.remove(h)
        c.execute("UPDATE users SET mfa_recovery = ? WHERE id = ?", (json.dumps(left), user["id"]))
        return True
    return False


def disable(c: Conn, user: dict) -> None:
    c.execute("UPDATE users SET mfa_secret = NULL, mfa_enabled_at = NULL, mfa_recovery = '[]', mfa_last_step = 0 WHERE id = ?", (user["id"],))


def recovery_left(user: dict) -> int:
    return len(json.loads(user.get("mfa_recovery") or "[]"))


# ---------------------------------------------------------------- the ticket between the two steps

def _ticket_key(cfg) -> bytes:
    return hashlib.sha256(("propelo-mfa-ticket|" + (cfg.secrets_key or "dev-only:" + cfg.database_url)).encode()).digest()


def ticket(cfg, uid: str, via: str, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + TICKET_SECONDS)
    body = f"{uid}.{exp}.{via}"
    sig = hmac.new(_ticket_key(cfg), body.encode(), hashlib.sha256).hexdigest()[:40]
    return base64.urlsafe_b64encode(f"{body}.{sig}".encode()).decode().rstrip("=")


def read_ticket(cfg, t: str, now: float | None = None) -> tuple[str, str] | None:
    try:
        raw = base64.urlsafe_b64decode(t + "=" * (-len(t) % 4)).decode()
        uid, exp, via, sig = raw.split(".")
    except (ValueError, UnicodeDecodeError):
        return None
    want = hmac.new(_ticket_key(cfg), f"{uid}.{exp}.{via}".encode(), hashlib.sha256).hexdigest()[:40]
    if not hmac.compare_digest(want, sig) or int(exp) < (now if now is not None else time.time()):
        return None
    return uid, via
