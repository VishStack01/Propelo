"""Sign in with a mobile number, through Twilio Verify.

Twilio Verify sends and checks the code, so the code never touches this service and Twilio's own fraud
checks apply. A code is only ever sent to a number already confirmed on an account (or, from Settings, to
the number a signed-in member is adding), so the sign-in form cannot be used to text strangers.
Off unless TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_VERIFY_SID are set.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .config import Config

VERIFY_API = "https://verify.twilio.com/v2/Services"


class PhoneError(RuntimeError):
    pass


def normalize(raw: str) -> str:
    """+<country code><number> (E.164), or "" when it isn't one. A leading 00 counts as +."""
    s = re.sub(r"[\s().\-]", "", str(raw or ""))
    if s.startswith("00"):
        s = "+" + s[2:]
    return s if re.fullmatch(r"\+[1-9]\d{7,14}", s) else ""


def mask(phone: str) -> str:
    """"+44 ••• •••• 1234": enough to recognise, not enough to copy."""
    return f"{phone[:3]} ••• •••• {phone[-4:]}" if phone and len(phone) > 7 else ""


class Verify:
    def __init__(self, cfg: Config, post: Callable[[str, dict, str], dict] | None = None):
        self.cfg = cfg
        self.post = post or self._post

    @property
    def enabled(self) -> bool:
        return self.cfg.phone_enabled

    def _post(self, url: str, form: dict, auth: str) -> dict:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST",
                                     headers={"Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - fixed https host
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
            except Exception:  # noqa: BLE001
                body = {}
            if e.code == 404 and "VerificationCheck" in url:
                return {"status": "expired"}  # Twilio answers 404 once a code has expired or been used
            raise PhoneError(f"Twilio {e.code}: {str(body.get('message') or '')[:160]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise PhoneError(f"Twilio unreachable: {e}") from e

    def _auth(self) -> str:
        return base64.b64encode(f"{self.cfg.twilio_account_sid}:{self.cfg.twilio_auth_token}".encode()).decode()

    def send(self, phone: str) -> None:
        out = self.post(f"{VERIFY_API}/{self.cfg.twilio_verify_sid}/Verifications", {"To": phone, "Channel": "sms"}, self._auth())
        if out.get("status") not in ("pending", "approved"):
            raise PhoneError(f"Twilio did not send a code: {out.get('status')}")

    def check(self, phone: str, code: str) -> bool:
        code = re.sub(r"\D", "", str(code or ""))[:10]
        if not 4 <= len(code) <= 10:
            return False
        out = self.post(f"{VERIFY_API}/{self.cfg.twilio_verify_sid}/VerificationCheck", {"To": phone, "Code": code}, self._auth())
        return out.get("status") == "approved"
