"""Two-step sign-in with an authenticator app."""

import base64
import time

import pytest

pytest.importorskip("fastapi")

from careeros.cloud import mfa  # noqa: E402

PW = "correct horse battery"


def test_totp_matches_rfc_6238():
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert mfa.code_at(secret, 59 // 30) == "287082"       # RFC 6238 vector 94287082, 6 digits
    assert mfa.code_at(secret, 1111111109 // 30) == "081804"
    step = mfa.check(secret, "287082", now=59)
    assert step == 1 and mfa.check(secret, "287082", last_step=step, now=59) == 0  # no replay
    assert mfa.check(secret, "287082", now=59 + 300) == 0                          # too old
    assert mfa.check(secret, "12", now=59) == 0


def test_ticket_is_signed_and_expires(cloud):
    t = mfa.ticket(cloud.cfg, "u1", "password", now=1000)
    assert mfa.read_ticket(cloud.cfg, t, now=1100) == ("u1", "password")
    assert mfa.read_ticket(cloud.cfg, t, now=1000 + mfa.TICKET_SECONDS + 1) is None
    assert mfa.read_ticket(cloud.cfg, t[:-2] + "xx", now=1100) is None


def _code(secret):
    return mfa.code_at(secret, int(time.time() // 30))


def test_turn_on_sign_in_with_code_and_recovery(cloud):
    u = cloud.user("asha@example.com")
    assert u.post("/api/me/mfa/setup", json={"password": "wrong"}).status_code == 403
    setup = u.post("/api/me/mfa/setup", json={"password": PW}).json()
    assert setup["uri"].startswith("otpauth://totp/Propelo:") and len(setup["secret"]) >= 32
    assert u.post("/api/me/mfa/enable", json={"code": "000000"}).status_code == 400
    r = u.post("/api/me/mfa/enable", json={"code": _code(setup["secret"])})
    assert r.status_code == 200
    codes = r.json()["recoveryCodes"]
    assert len(codes) == 10 and u.get("/api/me").json()["mfa"] is True

    c = cloud.client()
    r = c.post("/api/auth/login", json={"email": "asha@example.com", "password": PW})
    assert r.status_code == 200 and r.json()["mfa"] and "ticket" in r.json()
    assert c.get("/api/me").status_code == 401  # no session yet
    t = r.json()["ticket"]
    assert c.post("/api/auth/mfa", json={"ticket": t, "code": "000000"}).status_code == 401
    assert c.post("/api/auth/mfa", json={"ticket": "garbage", "code": "000000"}).json()["code"] == "mfa_expired"
    time.sleep(0)  # the app code from enable was used; a recovery code works once
    assert c.post("/api/auth/mfa", json={"ticket": t, "code": codes[0]}).status_code == 200
    assert c.get("/api/me").status_code == 200
    c2 = cloud.client()
    t2 = c2.post("/api/auth/login", json={"email": "asha@example.com", "password": PW}).json()["ticket"]
    assert c2.post("/api/auth/mfa", json={"ticket": t2, "code": codes[0]}).status_code == 401  # spent
    assert u.get("/api/me/mfa").json()["recoveryLeft"] == 9

    # Turning it off needs the password and a working code.
    assert u.post("/api/me/mfa/disable", json={"password": PW, "code": "000000"}).status_code == 400
    assert u.post("/api/me/mfa/disable", json={"password": PW, "code": codes[1]}).status_code == 200
    assert cloud.client().post("/api/auth/login", json={"email": "asha@example.com", "password": PW}).json()["ok"] is True


def test_brute_force_on_codes_is_limited(cloud):
    u = cloud.user("ravi@example.com")
    s = u.post("/api/me/mfa/setup", json={"password": PW}).json()
    u.post("/api/me/mfa/enable", json={"code": _code(s["secret"])})
    c = cloud.client()
    t = c.post("/api/auth/login", json={"email": "ravi@example.com", "password": PW}).json()["ticket"]
    codes = [c.post("/api/auth/mfa", json={"ticket": t, "code": f"{i:06d}"}).status_code for i in range(10)]
    assert 429 in codes


def test_staff_need_mfa_in_production(cloud, monkeypatch):
    cloud.cfg.secrets_key = "k" * 40
    admin = cloud.user("admin@example.com")
    assert admin.get("/api/staff/partners").status_code == 200  # development: not enforced
    cloud.cfg.secrets_key = "k" * 40
    monkeypatch.setattr(type(cloud.cfg), "is_production", property(lambda self: True))
    r = admin.get("/api/staff/partners")
    assert r.status_code == 403 and r.json()["code"] == "mfa_required"
    s = admin.post("/api/me/mfa/setup", json={"password": PW}).json()
    admin.post("/api/me/mfa/enable", json={"code": _code(s["secret"])})
    assert admin.get("/api/staff/partners").status_code == 200
    assert admin.post("/api/me/mfa/disable", json={"password": PW, "code": "x"}).json()["code"] == "mfa_required"
    # A page asks them to set it up instead of showing an error.
    other = cloud.user("staff2@example.com")
    with cloud.db.tx() as c:
        c.execute("UPDATE users SET is_staff = 1 WHERE email = ?", ("staff2@example.com",))
    r = other.get("/staff", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app#setup"


def test_admin_can_reset_a_lost_device(cloud):
    admin = cloud.user("admin@example.com")
    u = cloud.user("lost@example.com")
    s = u.post("/api/me/mfa/setup", json={"password": PW}).json()
    u.post("/api/me/mfa/enable", json={"code": _code(s["secret"])})
    assert u.post("/api/admin/mfa-reset", json={"email": "lost@example.com"}).status_code == 404
    assert admin.post("/api/admin/mfa-reset", json={"email": "lost@example.com"}).status_code == 200
    assert cloud.client().post("/api/auth/login", json={"email": "lost@example.com", "password": PW}).json()["ok"] is True


def test_pages_404_and_robots(cloud):
    c = cloud.client()
    r = c.get("/no-such-page", headers={"accept": "text/html"})
    assert r.status_code == 404 and "couldn't find that page" in r.text
    assert c.get("/api/no-such", headers={"accept": "text/html"}).headers["content-type"].startswith("application/json")
    r = c.get("/partner", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    r = c.get("/staff", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=/staff")
    assert "Disallow: /app" in c.get("/robots.txt").text
    assert "/business</loc>" in c.get("/sitemap.xml").text
    assert '<link rel="canonical"' in c.get("/privacy").text and "<title>Privacy policy" in c.get("/privacy").text
    assert "<title>Terms of service" in c.get("/terms").text
    assert c.get("/reset").headers.get("x-robots-tag") == "noindex"
