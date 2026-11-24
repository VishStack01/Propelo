"""Sign in with Google, GitHub or LinkedIn.

Each provider is asked for the least it can give: the member's name and a confirmed
email address. Nothing is posted, read or stored beyond that, and the access token is
dropped as soon as the email is known. A provider is offered only when its client id
and secret are set on the server.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import linkedin


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    authorize: str
    token: str
    scopes: str


PROVIDERS = {
    "google": Provider("google", "Google", "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token", "openid email profile"),
    "github": Provider("github", "GitHub", "https://github.com/login/oauth/authorize", "https://github.com/login/oauth/access_token", "read:user user:email"),
    "linkedin": Provider("linkedin", "LinkedIn", linkedin.AUTHORIZE, linkedin.TOKEN, linkedin.SCOPES),
}
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
GITHUB_USER = "https://api.github.com/user"
GITHUB_EMAILS = "https://api.github.com/user/emails"


def authorize_url(provider: str, client_id: str, redirect_uri: str, state: str) -> str:
    p = PROVIDERS[provider]
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state, "scope": p.scopes}
    if provider == "google":
        q["prompt"] = "select_account"
    return p.authorize + "?" + urllib.parse.urlencode(q)


def _get(url: str, token: str, timeout: float):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "Propelo"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def exchange(provider: str, code: str, redirect_uri: str, client_id: str, client_secret: str, timeout: float = 15) -> str:
    """The access token for an authorization code."""
    if provider == "linkedin":
        return linkedin.exchange(code, redirect_uri, client_id, client_secret)
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                   "client_id": client_id, "client_secret": client_secret}).encode()
    req = urllib.request.Request(PROVIDERS[provider].token, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": "Propelo"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())["access_token"]


def identity(provider: str, access_token: str, timeout: float = 15) -> dict:
    """{"email", "name", "verified"}: the email is empty when the provider did not share one."""
    if provider == "github":
        user = _get(GITHUB_USER, access_token, timeout)
        emails = _get(GITHUB_EMAILS, access_token, timeout)
        good = [e for e in emails if isinstance(e, dict) and e.get("verified") and e.get("email")]
        best = next((e for e in good if e.get("primary")), good[0] if good else None)
        return {"email": (best or {}).get("email", ""), "name": str(user.get("name") or user.get("login") or ""), "verified": bool(best)}
    info = linkedin.userinfo(access_token) if provider == "linkedin" else _get(GOOGLE_USERINFO, access_token, timeout)
    # Google always states email_verified; LinkedIn may leave it out, and only an explicit "no" is refused there.
    verified = info.get("email_verified") is True if provider == "google" else info.get("email_verified") is not False
    return {"email": str(info.get("email") or ""), "name": str(info.get("name") or ""), "verified": verified}
