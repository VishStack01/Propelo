"""The Propelo Cloud web app and API (FastAPI).

Pages: /login /signup /forgot /reset /verify (sign-in), / (the dashboard), /pricing,
       /privacy /terms /refunds /contact, plus the installable app's manifest, service worker and icons.
API:   /api/auth/*  /api/me*  /api/tokens*  /api/c/<collection>  /api/d/<collection>/<id>
       /api/assets*  /_blob/<id>  /api/agent/*  /api/admin/*  /api/health  /api/ready
       /api/billing* (plans; Razorpay for INR and Dodo Payments for USD: checkout, portal, webhooks)  /api/ai (AI actions, metered by plan)

Browser requests are authenticated by an HttpOnly session cookie and must send
the X-CareerOS-CSRF header on writes. The user's apply agent authenticates with
a computer key (Bearer cos_k_...) that can read the pipeline and report results
through /api/agent only.
"""

from __future__ import annotations

import hashlib
import html
from html import escape as html_escape
import json
import logging
import os
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from .. import evaluation as evaluation_mod
from .. import followups, llm
from ..dedupe import canonical_url, company_key
from ..scamcheck import check as scam_check
from . import mailer as mail
from . import linkedin as li_auth
from . import autosend, concierge, guarantee, mailbox, mfa, partners, passes, plans, repo, security
from .config import Config
from .db import Database, now_iso
from .ingest import feed_state
from .mailer import Mailer
from .storage import make_storage

log = logging.getLogger("careeros.api")
STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "cos_session"
_DOC_ID = re.compile(r"^[A-Za-z0-9_.:@+~-]{1,200}$")
_ASSET_ID = re.compile(r"^[a-f0-9]{32}$")


@dataclass
class Principal:
    user: dict
    kind: str  # "session" | "key"
    cred_id: str
    token: str

    @property
    def uid(self) -> str:
        return self.user["id"]




def _docx_text(data: bytes) -> str:
    """Paragraph text from a .docx (it's a zip of XML); no outside library needed."""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > 20 * 1024 * 1024:
                return ""
            xml = z.read(info).decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile, OSError):
        return ""
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    out = []
    for para in paras:
        t = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", para))
        if t.strip():
            out.append(html.unescape(t))
    return "\n".join(out)

def _origin(url: str) -> str:
    m = re.match(r"^(https?://[^/]+)", url or "")
    return m.group(1) if m else ""

def pdf_text(data: bytes, max_pages: int = 8, max_chars: int = 40000) -> str:
    """Best-effort text of an uploaded resume, so the user's agent can read it without the file."""
    try:
        import io

        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        out = []
        for page in reader.pages[:max_pages]:
            out.append(page.extract_text() or "")
            if sum(map(len, out)) > max_chars:
                break
        return re.sub(r"[ \t]+", " ", "\n".join(out)).strip()[:max_chars]
    except Exception:  # noqa: BLE001 - a resume that can't be read as text is still a valid upload
        return ""


def err(status: int, message: str, code: str = "") -> HTTPException:
    return HTTPException(status_code=status, detail={"error": message, "code": code} if code else {"error": message})


def _init_error_reporting(cfg: Config) -> None:
    """Optional error reporting (SENTRY_DSN, with `pip install sentry-sdk`). No request bodies, cookies,
    headers or user details are sent: only the error, its stack and the route."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk isn't installed; errors stay in the logs only.")
        return

    def scrub(event, hint):
        req = event.get("request") or {}
        for k in ("data", "cookies", "headers", "query_string", "env"):
            req.pop(k, None)
        event["request"] = req
        event.pop("user", None)
        return event
    sentry_sdk.init(dsn=dsn, environment=cfg.app_env, release=f"propelo@{__version__}", send_default_pii=False,
                    traces_sample_rate=float(os.environ.get("SENTRY_TRACES", "0") or 0), before_send=scrub, max_breadcrumbs=20)


def create_app(cfg: Config | None = None, db: Database | None = None) -> FastAPI:
    cfg = cfg or Config.from_env()
    problems = cfg.check()
    if problems:
        raise RuntimeError("Unsafe configuration:\n- " + "\n- ".join(problems))
    own_db = db is None
    db = db or Database(cfg.database_url, cfg.db_pool_min, cfg.db_pool_max)
    if cfg.is_production and db.pending_migrations():
        if own_db:
            db.close()  # exit at once instead of waiting on the pool's threads
        raise RuntimeError("Database migrations are pending. Run `careeros cloud migrate` before starting the app.")
    if not cfg.is_production:
        db.migrate(log=log.info)
    storage = make_storage(cfg, db)
    mailer = Mailer(cfg.smtp_url, cfg.mail_from, cfg.support_email)
    _init_error_reporting(cfg)
    app = FastAPI(title="Propelo Cloud", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.db, app.state.storage, app.state.mailer = cfg, db, storage, mailer
    hits: dict[str, deque] = defaultdict(deque)  # per-process API rate limiter

    # ------------------------------------------------------------ helpers
    def client_ip(request: Request) -> str:
        if cfg.trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else ""

    def send(c, to: str, subject_text: tuple[str, str]) -> None:
        subject, text = subject_text
        if mailer.url.startswith("console"):
            mailer.send(to, subject, text)  # development: straight to the outbox
        else:
            repo.enqueue(c, "send_email", {"to": to, "subject": subject, "text": text}, max_attempts=6)

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(COOKIE, token, max_age=cfg.session_ttl_days * 86400, httponly=True, secure=cfg.secure_cookies,
                            samesite="lax", path="/")

    def clear_cookie(response: Response) -> None:
        response.delete_cookie(COOKIE, path="/", secure=cfg.secure_cookies, httponly=True, samesite="lax")

    def limited(c, key: str, limit: int, seconds: int) -> None:
        if not security.hit(c, key, limit, seconds):
            raise err(429, "Too many attempts. Wait a few minutes and try again.", "rate_limited")

    def link(path: str, token: str) -> str:
        return f"{cfg.public_url}{path}#token={token}"  # the fragment never reaches server logs

    def principal(request: Request) -> Principal:
        auth = request.headers.get("authorization", "")
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        token = bearer or request.cookies.get(COOKIE, "")
        if not token:
            raise err(401, "Sign in to continue.", "unauthenticated")
        with db.tx() as c:
            if token.startswith("cos_k_"):
                found = repo.api_token_user(c, token)
            elif token.startswith("cos_s_"):
                found = repo.session_user(c, token)
            else:
                found = None
        if not found:
            raise err(401, "Your session has ended. Sign in again.", "unauthenticated")
        user, cred = found
        if not bearer and request.method not in ("GET", "HEAD", "OPTIONS"):
            # Cookie-authenticated writes need the custom header (a cross-site page can't set it
            # without a CORS preflight this server never grants) and, when sent, a matching Origin.
            if request.headers.get("x-careeros-csrf") != "1":
                raise err(403, "Missing CSRF header.", "csrf")
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != cfg.public_url and not cfg.public_url.startswith("http://127.0.0.1"):
                raise err(403, "Cross-site request refused.", "csrf")
        if not user["email_verified_at"]:
            raise err(403, "Confirm your email first.", "unverified")
        key = cred["id"]
        t = time.monotonic()
        if len(hits) > 20000:  # forget idle credentials so the limiter's memory stays bounded
            for k in [k for k, q in hits.items() if not q or q[-1] < t - 300]:
                hits.pop(k, None)
        q = hits[key]
        while q and q[0] < t - 300:
            q.popleft()
        if len(q) >= 1500:
            raise err(429, "Too many requests. Slow down for a minute.", "rate_limited")
        q.append(t)
        return Principal(user=user, kind=cred["kind"], cred_id=cred["id"], token=token)

    def csrf(request: Request) -> None:
        """Auth forms send the header as well, so another site can't sign a visitor in to an account it controls."""
        if request.headers.get("x-careeros-csrf") != "1":
            raise err(403, "Missing CSRF header.", "csrf")

    def session_only(p: Principal = Depends(principal)) -> Principal:
        if p.kind != "session":
            raise err(403, "Computer keys can't do this. Sign in on the dashboard.", "forbidden")
        return p

    def needs_mfa(p: Principal) -> None:
        # Staff and admins can see other people's data and approve money: in production they need two-step sign-in.
        if cfg.is_production and not mfa.enabled(p.user):
            raise err(403, "Turn on two-step sign-in in Settings first. Staff and admin pages need it.", "mfa_required")

    def admin_only(p: Principal = Depends(session_only)) -> Principal:
        if not p.user["is_admin"]:
            raise err(404, "Not found.")
        needs_mfa(p)
        return p

    def staff_only(p: Principal = Depends(session_only)) -> Principal:
        if not (p.user["is_admin"] or p.user.get("is_staff")):
            raise err(404, "Not found.")
        needs_mfa(p)
        return p

    def check_col(col: str, did: str | None = None) -> None:
        if col not in repo.COLLECTIONS:
            raise err(404, "Not found.")
        if did is not None and not _DOC_ID.match(did):
            raise err(404, "Not found.")

    def html(name: str, nonce: str, canonical: str = "") -> HTMLResponse:
        text = (STATIC / name).read_text(encoding="utf-8")
        if canonical:
            text = text.replace("</title>", f'</title>\n<link rel="canonical" href="{cfg.public_url}{canonical}">', 1)
        return HTMLResponse(text.replace("<script>", f'<script nonce="{nonce}">'))

    # ------------------------------------------------------------ middleware
    @app.middleware("http")
    async def frame(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
        t0 = time.perf_counter()
        n = request.headers.get("content-length")
        cap = (cfg.max_upload_mb + 1) * 1024 * 1024 if request.url.path.startswith("/api/assets") else (cfg.max_doc_kb + 64) * 1024
        if n and n.isdigit() and int(n) > cap:
            response = JSONResponse({"error": "Request too large."}, status_code=413)
        else:
            request.state.nonce = secrets.token_urlsafe(16)
            response = await call_next(request)
        nonce = getattr(request.state, "nonce", "")
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if cfg.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if not request.url.path.startswith("/_blob/"):
            logo_src = (" " + _origin(cfg.jobs_site_url)) if cfg.jobs_site_url else ""
            response.headers["Content-Security-Policy"] = (
                f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; manifest-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                f"font-src https://fonts.gstatic.com; img-src 'self' data:{logo_src}; connect-src 'self'{logo_src}; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'; object-src 'none'")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        log.info(json.dumps({"rid": rid, "method": request.method, "path": request.url.path, "status": response.status_code,
                             "ms": round((time.perf_counter() - t0) * 1000, 1)}))
        return response

    def wants_page(request: Request) -> bool:
        return request.method == "GET" and not request.url.path.startswith("/api/") and "text/html" in request.headers.get("accept", "")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        # A person in a browser gets a page: sign-in for pages that need it, a real 404 page for wrong links.
        if wants_page(request) and exc.status_code == 401:
            return RedirectResponse(f"/login?next={quote(request.url.path, safe='/')}", status_code=303)
        if wants_page(request) and exc.status_code == 403 and isinstance(exc.detail, dict) and exc.detail.get("code") == "mfa_required":
            return RedirectResponse("/app#setup", status_code=303)
        if wants_page(request) and exc.status_code == 404:
            return HTMLResponse((STATIC / "notfound.html").read_text(encoding="utf-8"), status_code=404)
        body = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        # The app's public pages can be found; the private app, staff pages and the API cannot.
        text = ("User-agent: *\nAllow: /business\nAllow: /pricing\nAllow: /privacy\nAllow: /terms\nAllow: /refunds\nAllow: /contact\n"
                "Allow: /signup\nAllow: /login\nDisallow: /app\nDisallow: /partner\nDisallow: /staff\nDisallow: /join/\nDisallow: /api/\n"
                "Disallow: /verify\nDisallow: /reset\nDisallow: /forgot\nDisallow: /optout\n"
                f"Sitemap: {cfg.public_url}/sitemap.xml\n")
        return Response(text, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap():
        pages = ("/business", "/pricing", "/signup", "/privacy", "/terms", "/refunds", "/contact")
        urls = "".join(f"<url><loc>{cfg.public_url}{x}</loc></url>" for x in pages)
        return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                        media_type="application/xml", headers={"Cache-Control": "public, max-age=86400"})

    def guess_currency(request: Request) -> str:
        q = (request.query_params.get("currency") or "").upper()
        if q in plans.CURRENCIES:
            return q
        country = request.headers.get("cf-ipcountry", "") or request.headers.get("x-country", "")
        if country and country.upper() not in ("XX", "T1"):
            return plans.currency_for(country)
        # No country from the edge: rupees, unless only dollar payments are switched on.
        return "USD" if cfg.dodo_enabled and not cfg.razorpay_enabled else "INR"

    # ------------------------------------------------------------ pages
    @app.get("/", include_in_schema=False)
    def home(request: Request):
        if not request.cookies.get(COOKIE):
            return RedirectResponse("/login", status_code=303)
        page = html("dashboard.html", request.state.nonce)
        page.headers["X-Robots-Tag"] = "noindex"
        return page

    @app.get("/app", include_in_schema=False)
    def dashboard(request: Request):
        return home(request)

    def auth_page(request: Request):
        path = request.url.path
        page = html("auth.html", request.state.nonce, canonical=path if path in ("/login", "/signup") else "")
        if path not in ("/login", "/signup"):
            page.headers["X-Robots-Tag"] = "noindex"  # one-time links: reset, verify, forgot
        return page

    LEGAL = {"/privacy": ("Privacy policy", "What Propelo collects, why, who it is shared with, how long it is kept and how to delete it."),
             "/terms": ("Terms of service", "The terms for using Propelo, including plans, business accounts, guarantees and acceptable use."),
             "/refunds": ("Refunds and cancellation", "How to cancel a Propelo plan, when payments are refunded and how guarantees pay out."),
             "/contact": ("Contact", "How to reach the people behind Propelo for support, privacy requests, security reports and billing.")}

    def legal_page(request: Request):
        title, desc = LEGAL.get(request.url.path, LEGAL["/privacy"])
        text = (STATIC / "legal.html").read_text(encoding="utf-8").replace("<script>", f'<script nonce="{request.state.nonce}">')
        text = text.replace("<title>Propelo · Privacy, terms and refunds</title>",
                            f'<title>{title} · Propelo</title>\n<meta name="description" content="{desc}">\n'
                            f'<link rel="canonical" href="{cfg.public_url}{request.url.path}">', 1)
        support = html_escape(cfg.support_email)
        if support:
            text = text.replace("{{SUPPORT_EMAIL}}", support)
        else:
            text = text.replace('<a href="mailto:{{SUPPORT_EMAIL}}">{{SUPPORT_EMAIL}}</a>', "the address on the emails this service sends you")
        return HTMLResponse(text.replace("{{COMPANY}}", html_escape(cfg.company_name)))

    for path in ("/login", "/signup", "/forgot", "/reset", "/verify"):
        app.add_api_route(path, auth_page, methods=["GET"], include_in_schema=False)
    for path in ("/privacy", "/terms", "/refunds", "/contact"):
        app.add_api_route(path, legal_page, methods=["GET"], include_in_schema=False)

    @app.get("/pricing", include_in_schema=False)
    def pricing(request: Request):
        # Rendered on the server from the live plan settings, so the page never waits on a fetch.
        cur = guess_currency(request)
        cards = []
        for pl in plans.catalog(cfg):
            per = "<small> / month</small>" if pl["priceInr"] else ""
            price = (f'<span class="inr">₹{pl["priceInr"]:,}{per}</span>'
                     f'<span class="usd">${pl["priceUsd"] if pl["priceInr"] else "0"}{per}</span>')
            items = "".join(f"<li>{html_escape(f)}</li>" for f in pl["features"])
            cls = "btn" if pl["id"] != "free" else "btn light"
            # A paid card goes straight to checkout: create the account, confirm the email, and the payment page opens.
            buy = pl["id"] != "free" and cfg.billing_enabled
            go = f'/signup?next=%2Fapp%3Fbuy%3D{pl["id"]}' if buy else "/signup"
            label = f'Get {html_escape(pl["name"])}' if buy else "Start free"
            cards.append(f'<article class="plan {pl["id"]}"><h2>{html_escape(pl["name"])}</h2>'
                         f'<div class="price">{price}</div><ul>{items}</ul><a class="{cls}" href="{go}">{label}</a></article>')
        offer = passes.offer(cfg)
        if offer and offer["currencies"]:
            cards.append('<article class="plan pass"><h2>Pro pass</h2>'
                         f'<div class="price"><span class="inr">₹{offer["priceInr"]:,}<small> once</small></span><span class="usd">${offer["priceUsd"]}<small> once</small></span></div>'
                         f'<ul><li>Everything in Pro for {offer["days"]} days</li><li>Pay once by UPI or card</li><li>Nothing renews, nothing to cancel</li></ul>'
                         '<a class="btn" href="/signup?next=%2Fapp%3Fbuy%3Dpass">Get the pass</a></article>')
        extras = ""
        for ad in plans.addons(cfg):
            if ad["priceInr"]:
                price = f'<span class="inr">₹{ad["priceInr"]:,}</span><span class="usd">${ad["priceUsd"]}</span>'
            else:
                price = '<span>No upfront fee</span>'
            extras += (f'<article class="addon"><div><h3>{html_escape(ad["name"])}</h3><p>{html_escape(ad["line"])}</p></div>'
                       f'<p class="aprice">{price}<small>{html_escape(ad["when"])}</small></p></article>')
        if extras:
            extras = ('<section class="addons"><h2>Guarantees for Pro and Ultra members</h2><p class="note">Not part of any plan. Apply in the app; '
                      'a person on our team reviews every application. <a href="/terms#guarantees">Guarantee terms</a></p>' + extras + '</section>')
        text = (STATIC / "pricing.html").read_text(encoding="utf-8").replace("<!--PLANS-->", "".join(cards)).replace("<!--ADDONS-->", extras) \
            .replace('<body data-cur="INR">', f'<body data-cur="{cur}">', 1).replace("<script>", f'<script nonce="{request.state.nonce}">') \
            .replace("</title>", f'</title>\n<link rel="canonical" href="{cfg.public_url}/pricing">', 1)
        return HTMLResponse(text)

    @app.get("/.well-known/security.txt", include_in_schema=False)
    def security_txt():
        contact = f"mailto:{cfg.security_email or cfg.support_email}" if (cfg.security_email or cfg.support_email) else \
            "https://github.com/VishStack01/careeros/security/advisories/new"
        expires = (datetime.now(timezone.utc) + timedelta(days=180)).strftime("%Y-%m-%dT00:00:00.000Z")
        body = (f"Contact: {contact}\nExpires: {expires}\nPreferred-Languages: en\n"
                f"Policy: https://github.com/VishStack01/careeros/blob/main/SECURITY.md\nCanonical: {cfg.public_url}/.well-known/security.txt\n")
        return Response(body, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})

    # The installable app: manifest, service worker, icons and the offline page.
    APP_STATIC = STATIC / "app"

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return Response((APP_STATIC / "manifest.webmanifest").read_bytes(), media_type="application/manifest+json",
                        headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return Response((APP_STATIC / "sw.js").read_bytes(), media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/offline", include_in_schema=False)
    def offline():
        return HTMLResponse((APP_STATIC / "offline.html").read_text(encoding="utf-8"), headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/icons/{name}", include_in_schema=False)
    def icon(name: str):
        if not re.match(r"^[a-z0-9-]{1,40}\.png$", name) or not (APP_STATIC / "icons" / name).is_file():
            raise err(404, "Not found.")
        return Response((APP_STATIC / "icons" / name).read_bytes(), media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/apple-touch-icon.png", include_in_schema=False)
    def apple_icon():
        return icon("apple-touch-icon.png")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="#FF85BA"/><path d="M33 34h10v4.6c3-3.6 7.2-5.6 12.2-5.6 9.6 0 16.8 7.6 16.8 17.6S64.8 68.2 55.2 68.2c-5 0-9.2-2-12.2-5.4V82H33zm21 25.4c5 0 8.6-3.8 8.6-8.8s-3.6-8.8-8.6-8.8-8.6 3.8-8.6 8.8 3.6 8.8 8.6 8.8z" fill="#151515"/></svg>'
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    # ------------------------------------------------------------ health
    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "mode": "cloud", "signup": cfg.signup_mode}

    @app.get("/api/ready")
    def ready():
        try:
            pending = db.pending_migrations()
            with db.tx() as c:
                oldest = c.scalar("SELECT MIN(run_after) AS t FROM tasks WHERE status = 'queued'")
                state = feed_state(c)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": type(e).__name__}, status_code=503)
        ok = not pending
        return JSONResponse({"ok": ok, "pendingMigrations": pending, "oldestQueuedTask": oldest,
                             "feedGeneratedAt": state.get("generatedAt"), "lastIngestAt": state.get("ingestedAt")},
                            status_code=200 if ok else 503)

    # ------------------------------------------------------------ auth
    @app.post("/api/auth/signup", status_code=202, dependencies=[Depends(csrf)])
    def signup(request: Request, body: dict = Body(default={})):
        email = security.normalize_email(str(body.get("email", "")))
        password, name = str(body.get("password", "")), str(body.get("name", "")).strip()[:80]
        if not security.valid_email(email):
            raise err(400, "Enter a valid email address.", "email")
        problem = security.password_problem(password, email)
        if problem:
            raise err(400, problem, "password")
        if not cfg.signup_allowed(email):
            raise err(403, "Sign-up is by invitation right now.", "closed")
        ip = client_ip(request)
        # Where to land after confirming the email (a join link, the business page). Same-site paths only.
        nxt = str(body.get("next") or "")[:200]
        nxt = nxt if re.fullmatch(r"/(?!/)[A-Za-z0-9/_?=&.%-]*", nxt) else ""

        def vlink(token: str) -> str:
            return link("/verify", token) + (f"&next={quote(nxt, safe='')}" if nxt else "")
        pw_hash = security.hash_password(password, cfg.password_iterations)
        with db.tx() as c:
            limited(c, "signup:" + security.ip_key(ip), 10, 3600)
            limited(c, "signup-email:" + hashlib.sha256(email.encode()).hexdigest()[:24], 3, 3600)
            existing = repo.user_by_email(c, email)
            if existing and existing["email_verified_at"]:
                send(c, email, mail.already_registered(f"{cfg.public_url}/forgot"))
            elif existing:
                token = repo.issue_link_token(c, existing["id"], "verify", timedelta(hours=24))
                send(c, email, mail.verify_email(existing["name"], vlink(token)))
            else:
                uid = repo.create_user(c, email, name, pw_hash, is_admin=bool(cfg.bootstrap_admin_email) and email == cfg.bootstrap_admin_email,
                                       source=body.get("src"))
                token = repo.issue_link_token(c, uid, "verify", timedelta(hours=24))
                send(c, email, mail.verify_email(name, vlink(token)))
                repo.audit(c, uid, "signup", ip)
        return {"ok": True, "message": "Check your inbox for a link to confirm your email."}

    @app.post("/api/auth/verify", dependencies=[Depends(csrf)])
    def verify(request: Request, response: Response, body: dict = Body(default={})):
        ip = client_ip(request)
        with db.tx() as c:
            limited(c, "verify:" + security.ip_key(ip), 30, 3600)
        with db.tx() as c:
            uid = repo.consume_link_token(c, str(body.get("token", "")), "verify")
            if not uid:
                raise err(400, "That link has expired or was already used. Sign in to get a new one.", "bad_token")
            c.execute("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?), updated_at = ? WHERE id = ?", (now_iso(), now_iso(), uid))
            token = repo.create_session(c, uid, cfg.session_ttl_days, ip, request.headers.get("user-agent", ""))
            repo.enqueue(c, "match_user", user_id=uid, dedupe_key=f"match:{uid}", max_attempts=3)
            repo.audit(c, uid, "email-verified", ip)
            user = repo.user_by_id(c, uid)
        set_session_cookie(response, token)
        return {"ok": True, "user": repo.public_user(user)}

    @app.post("/api/auth/login", dependencies=[Depends(csrf)])
    def login(request: Request, response: Response, body: dict = Body(default={})):
        email = security.normalize_email(str(body.get("email", "")))
        password = str(body.get("password", ""))
        ip = client_ip(request)
        with db.tx() as c:
            limited(c, "login-ip:" + security.ip_key(ip), 30, 900)
            limited(c, "login-email:" + hashlib.sha256(email.encode()).hexdigest()[:24], 10, 900)
            user = repo.user_by_email(c, email)
        if not user:
            security.dummy_verify(cfg.password_iterations)
            raise err(401, "Email or password is incorrect.", "bad_credentials")
        if not security.verify_password(password, user["password_hash"]) or user["disabled_at"]:
            with db.tx() as c:
                repo.audit(c, user["id"], "login-failed", ip)
            raise err(401, "Email or password is incorrect.", "bad_credentials")
        if not user["email_verified_at"]:
            raise err(403, "Confirm your email first. We can send the link again.", "unverified")
        with db.tx() as c:
            if security.needs_rehash(user["password_hash"], cfg.password_iterations):
                c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(password, cfg.password_iterations), user["id"]))
            if mfa.enabled(user):
                # Two-step sign-in: no session until the code from the authenticator app is checked.
                return {"ok": False, "mfa": True, "ticket": mfa.ticket(cfg, user["id"], "password")}
            token = repo.create_session(c, user["id"], cfg.session_ttl_days, ip, request.headers.get("user-agent", ""))
            repo.audit(c, user["id"], "login", ip)
        set_session_cookie(response, token)
        return {"ok": True, "user": repo.public_user(user)}

    @app.post("/api/auth/mfa", dependencies=[Depends(csrf)])
    def login_mfa(request: Request, response: Response, body: dict = Body(default={})):
        got = mfa.read_ticket(cfg, str(body.get("ticket") or "")[:400])
        if not got:
            raise err(401, "That sign-in took too long. Start again.", "mfa_expired")
        uid, via = got
        ip = client_ip(request)
        with db.tx() as c:  # its own transaction, so a wrong code still counts toward the limit
            limited(c, "mfa:" + uid, 8, 900)
        with db.tx() as c:
            user = repo.user_by_id(c, uid)
            if not user or user["disabled_at"] or not mfa.enabled(user):
                raise err(401, "That sign-in took too long. Start again.", "mfa_expired")
            if not mfa.verify(c, cfg, user, str(body.get("code") or "")[:20]):
                repo.audit(c, uid, "login-mfa-failed", ip)
                raise err(401, "That code didn't work. Use the newest code in your authenticator app, or a recovery code.", "bad_code")
            token = repo.create_session(c, uid, cfg.session_ttl_days, ip, request.headers.get("user-agent", ""))
            repo.audit(c, uid, "login-" + via if via != "password" else "login", ip, {"mfa": True})
        set_session_cookie(response, token)
        return {"ok": True, "user": repo.public_user(user)}

    # ------------------------------------------------------------ Sign in with LinkedIn (OpenID Connect)
    LI_STATE = "careeros_li_state"

    def li_redirect_uri() -> str:
        return f"{cfg.public_url}/api/auth/linkedin/callback"

    @app.get("/api/auth/providers")
    def auth_providers():
        return {"linkedin": cfg.linkedin_enabled}

    @app.get("/api/auth/linkedin/start")
    def linkedin_start():
        if not cfg.linkedin_enabled:
            raise err(404, "Sign in with LinkedIn isn't set up on this server.", "not_configured")
        state = secrets.token_urlsafe(24)
        resp = RedirectResponse(li_auth.authorize_url(cfg.linkedin_client_id, li_redirect_uri(), state), status_code=303)
        resp.set_cookie(LI_STATE, state, max_age=600, httponly=True, secure=cfg.secure_cookies, samesite="lax", path="/api/auth/linkedin")
        return resp

    @app.get("/api/auth/linkedin/callback")
    def linkedin_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        def back(msg: str):
            resp = RedirectResponse(f"/login#error={msg}", status_code=303)
            resp.delete_cookie(LI_STATE, path="/api/auth/linkedin")
            return resp
        if not cfg.linkedin_enabled:
            raise err(404, "Sign in with LinkedIn isn't set up on this server.", "not_configured")
        expected = request.cookies.get(LI_STATE, "")
        if error or not code or not expected or not secrets.compare_digest(expected, state):
            return back("linkedin_cancelled" if error else "linkedin_state")
        ip = client_ip(request)
        with db.tx() as c:
            limited(c, "linkedin:" + security.ip_key(ip), 30, 3600)
        try:
            info = li_auth.userinfo(li_auth.exchange(code, li_redirect_uri(), cfg.linkedin_client_id, cfg.linkedin_client_secret))
        except Exception:  # noqa: BLE001  a refused or expired code
            return back("linkedin_failed")
        email = security.normalize_email(str(info.get("email") or ""))
        if not security.valid_email(email) or info.get("email_verified") is False:
            return back("linkedin_no_email")
        name = str(info.get("name") or "").strip()[:80]
        with db.tx() as c:
            user = repo.user_by_email(c, email)
            if user and user["disabled_at"]:
                return back("disabled")
            if not user:
                if not cfg.signup_allowed(email):
                    return back("closed")
                # No password: this account signs in with LinkedIn (or sets one through "Forgot password").
                uid = repo.create_user(c, email, name, "!linkedin", is_admin=bool(cfg.bootstrap_admin_email) and email == cfg.bootstrap_admin_email)
                repo.enqueue(c, "match_user", user_id=uid, dedupe_key=f"match:{uid}", max_attempts=3)
                repo.audit(c, uid, "signup-linkedin", ip)
            else:
                uid = user["id"]
            c.execute("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?), updated_at = ? WHERE id = ?", (now_iso(), now_iso(), uid))
            if user and mfa.enabled(user):
                resp = RedirectResponse(f"/login#mfa={mfa.ticket(cfg, uid, 'linkedin')}", status_code=303)
                resp.delete_cookie(LI_STATE, path="/api/auth/linkedin")
                return resp
            token = repo.create_session(c, uid, cfg.session_ttl_days, ip, request.headers.get("user-agent", ""))
            repo.audit(c, uid, "login-linkedin", ip)
        resp = RedirectResponse("/app", status_code=303)
        resp.delete_cookie(LI_STATE, path="/api/auth/linkedin")
        set_session_cookie(resp, token)
        return resp

    @app.post("/api/auth/resend", status_code=202, dependencies=[Depends(csrf)])
    def resend(request: Request, body: dict = Body(default={})):
        email = security.normalize_email(str(body.get("email", "")))
        with db.tx() as c:
            limited(c, "resend:" + security.ip_key(client_ip(request)), 10, 3600)
            limited(c, "resend-email:" + hashlib.sha256(email.encode()).hexdigest()[:24], 3, 3600)
            user = repo.user_by_email(c, email)
            if user and not user["email_verified_at"]:
                token = repo.issue_link_token(c, user["id"], "verify", timedelta(hours=24))
                send(c, email, mail.verify_email(user["name"], link("/verify", token)))
        return {"ok": True, "message": "If that account needs confirming, a new link is on its way."}

    @app.post("/api/auth/forgot", status_code=202, dependencies=[Depends(csrf)])
    def forgot(request: Request, body: dict = Body(default={})):
        email = security.normalize_email(str(body.get("email", "")))
        with db.tx() as c:
            limited(c, "forgot:" + security.ip_key(client_ip(request)), 10, 3600)
            limited(c, "forgot-email:" + hashlib.sha256(email.encode()).hexdigest()[:24], 3, 3600)
            user = repo.user_by_email(c, email)
            if user and not user["disabled_at"]:
                token = repo.issue_link_token(c, user["id"], "reset", timedelta(hours=1))
                send(c, email, mail.reset_password(link("/reset", token)))
        return {"ok": True, "message": "If an account uses that email, a reset link is on its way."}

    @app.post("/api/auth/reset", dependencies=[Depends(csrf)])
    def reset(request: Request, response: Response, body: dict = Body(default={})):
        password, ip = str(body.get("password", "")), client_ip(request)
        with db.tx() as c:
            limited(c, "reset:" + security.ip_key(ip), 20, 3600)
        with db.tx() as c:
            uid = repo.consume_link_token(c, str(body.get("token", "")), "reset")
            if not uid:
                raise err(400, "That link has expired or was already used. Ask for a new one.", "bad_token")
            user = repo.user_by_id(c, uid)
            problem = security.password_problem(password, user["email"])
            if problem:
                raise err(400, problem, "password")
            now = now_iso()
            c.execute("UPDATE users SET password_hash = ?, password_changed_at = ?, email_verified_at = COALESCE(email_verified_at, ?), updated_at = ? WHERE id = ?",
                      (security.hash_password(password, cfg.password_iterations), now, now, now, uid))
            repo.revoke_all_sessions(c, uid)
            token = repo.create_session(c, uid, cfg.session_ttl_days, ip, request.headers.get("user-agent", ""))
            send(c, user["email"], mail.password_changed())
            repo.audit(c, uid, "password-reset", ip)
        set_session_cookie(response, token)
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE, "")
        if token and request.headers.get("x-careeros-csrf") == "1":
            with db.tx() as c:
                repo.revoke_session(c, token)
        clear_cookie(response)
        return {"ok": True}

    # ------------------------------------------------------------ me
    @app.get("/api/me")
    def me(p: Principal = Depends(principal)):
        with db.tx() as c:
            used = repo.storage_used(c, p.uid)
            state = feed_state(c)
            plan = plans.plan_of(c, p.user)
            ai = plans.ai_status(c, cfg, p.user)
            seat = partners.student_of(c, p.uid)
            partner_admin = bool(partners.admin_partners(c, p.uid))
        quota = plans.plan_info(cfg, plan)["storageMb"]
        return dict(repo.public_user(p.user), via=p.kind, plan=plan, ai=ai, billing=cfg.billing_enabled,
                    partner=partners.branding(seat), partnerAdmin=partner_admin, supportEmail=cfg.support_email,
                    storage={"usedBytes": used, "quotaBytes": quota * 1024 * 1024}, jobsSite=cfg.jobs_site_url,
                    feed={"generatedAt": state.get("generatedAt"), "inventory": state.get("records"), "companies": state.get("companies")})

    @app.patch("/api/me")
    def update_me(body: dict = Body(default={}), p: Principal = Depends(session_only)):
        name = str(body.get("name", p.user["name"])).strip()[:80]
        with db.tx() as c:
            c.execute("UPDATE users SET name = ?, updated_at = ? WHERE id = ?", (name, now_iso(), p.uid))
        return {"ok": True}

    @app.get("/api/me/mfa")
    def mfa_status(p: Principal = Depends(session_only)):
        return {"enabled": mfa.enabled(p.user), "recoveryLeft": mfa.recovery_left(p.user), "required": bool(p.user["is_admin"] or p.user.get("is_staff"))}

    @app.post("/api/me/mfa/setup")
    def mfa_setup(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        has_password = not str(p.user["password_hash"]).startswith("!")
        if has_password and not security.verify_password(str(body.get("password") or ""), p.user["password_hash"]):
            raise err(403, "Your password is incorrect.", "bad_credentials")
        with db.tx() as c:
            limited(c, "mfa-setup:" + p.uid, 10, 3600)
            got = mfa.begin(c, cfg, p.user)
            repo.audit(c, p.uid, "mfa-setup", client_ip(request))
        return got

    @app.post("/api/me/mfa/enable")
    def mfa_enable(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        with db.tx() as c:
            limited(c, "mfa-enable:" + p.uid, 10, 900)
        with db.tx() as c:
            user = repo.user_by_id(c, p.uid)
            codes = mfa.confirm(c, cfg, user, str(body.get("code") or ""))
            if not codes:
                raise err(400, "That code didn't work. Check the time on your phone and try the newest code.", "bad_code")
            repo.audit(c, p.uid, "mfa-enabled", client_ip(request))
        return {"enabled": True, "recoveryCodes": codes}

    @app.post("/api/me/mfa/disable")
    def mfa_disable(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        if p.user["is_admin"] or p.user.get("is_staff"):
            if cfg.is_production:
                raise err(403, "Staff and admin accounts must keep two-step sign-in on.", "mfa_required")
        with db.tx() as c:
            limited(c, "mfa-disable:" + p.uid, 8, 900)
        with db.tx() as c:
            user = repo.user_by_id(c, p.uid)
            has_password = not str(user["password_hash"]).startswith("!")
            if has_password and not security.verify_password(str(body.get("password") or ""), user["password_hash"]):
                raise err(403, "Your password is incorrect.", "bad_credentials")
            if not mfa.verify(c, cfg, user, str(body.get("code") or "")):
                raise err(400, "That code didn't work.", "bad_code")
            mfa.disable(c, user)
            repo.audit(c, p.uid, "mfa-disabled", client_ip(request))
        return {"enabled": False}

    @app.post("/api/admin/mfa-reset")
    def admin_mfa_reset(request: Request, body: dict = Body(...), p: Principal = Depends(admin_only)):
        """For someone who lost their phone and recovery codes, after you have checked who they are."""
        email = security.normalize_email(str(body.get("email") or ""))
        with db.tx() as c:
            u = repo.user_by_email(c, email)
            if not u:
                raise err(404, "No account with that email.")
            mfa.disable(c, u)
            repo.audit(c, u["id"], "mfa-reset-by-admin", client_ip(request), {"by": p.uid})
        return {"ok": True}

    @app.post("/api/me/password")
    def change_password(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        if not security.verify_password(str(body.get("current", "")), p.user["password_hash"]):
            raise err(400, "Your current password is incorrect.", "bad_credentials")
        new = str(body.get("new", ""))
        problem = security.password_problem(new, p.user["email"])
        if problem:
            raise err(400, problem, "password")
        with db.tx() as c:
            now = now_iso()
            c.execute("UPDATE users SET password_hash = ?, password_changed_at = ?, updated_at = ? WHERE id = ?",
                      (security.hash_password(new, cfg.password_iterations), now, now, p.uid))
            repo.revoke_all_sessions(c, p.uid, except_id=p.cred_id)
            send(c, p.user["email"], mail.password_changed())
            repo.audit(c, p.uid, "password-changed", client_ip(request))
        return {"ok": True}

    @app.post("/api/me/logout-all")
    def logout_all(response: Response, p: Principal = Depends(session_only)):
        with db.tx() as c:
            repo.revoke_all_sessions(c, p.uid)
            repo.audit(c, p.uid, "logout-all")
        clear_cookie(response)
        return {"ok": True}

    @app.get("/api/me/export")
    def export(request: Request, p: Principal = Depends(session_only)):
        with db.tx() as c:
            data = {
                "exportedAt": now_iso(), "account": repo.public_user(p.user),
                "documents": {col: repo.list_docs(c, p.uid, col) for col in sorted(repo.COLLECTIONS)},
                "files": [dict(a, download=f"{cfg.public_url}/_blob/{a['id']}") for a in repo.list_assets(c, p.uid)],
                "applications": c.all("SELECT job_id, state, attempts, receipt, created_at, updated_at FROM applications WHERE user_id = ?", (p.uid,)),
                "computerKeys": repo.list_api_tokens(c, p.uid),
                "sessions": c.all("SELECT created_at, last_seen_at, expires_at, revoked_at, user_agent FROM sessions WHERE user_id = ?", (p.uid,)),
                "securityEvents": c.all("SELECT at, kind, detail FROM audit_events WHERE user_id = ? ORDER BY at", (p.uid,)),
                "plan": {k: v for k, v in plans.billing_view(c, cfg, p.user).items() if k != "plans"},
                "aiKey": plans.public_key(c, p.uid),
                "aiUsage": c.all("SELECT period, hosted, own FROM ai_usage WHERE user_id = ? ORDER BY period", (p.uid,)),
                "featureUsage": c.all("SELECT period, feature, count FROM feature_usage WHERE user_id = ? ORDER BY period", (p.uid,)),
            }
            repo.audit(c, p.uid, "export", client_ip(request))
        return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="careeros-export.json"'})

    @app.post("/api/me/delete")
    def delete_account(response: Response, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        if str(body.get("confirm", "")) != "DELETE" or not security.verify_password(str(body.get("password", "")), p.user["password_hash"]):
            raise err(400, "Type DELETE and enter your password to delete your account.", "confirm")
        with db.tx() as c:
            c.execute("DELETE FROM users WHERE id = ?", (p.uid,))  # cascades to every per-user table
        storage.delete_user(p.uid)
        log.info(json.dumps({"event": "account-deleted"}))
        clear_cookie(response)
        return {"ok": True}

    # ------------------------------------------------------------ computer keys
    @app.get("/api/tokens")
    def tokens(p: Principal = Depends(session_only)):
        with db.tx() as c:
            return {"keys": repo.list_api_tokens(c, p.uid)}

    @app.post("/api/tokens", status_code=201)
    def new_key(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        name = str(body.get("name", "")).strip()[:60] or "My computer"
        with db.tx() as c:
            if len(repo.list_api_tokens(c, p.uid)) >= 5:
                raise err(400, "You have 5 computer keys. Remove one first.", "limit")
            token, meta = repo.create_api_token(c, p.uid, name)
            repo.audit(c, p.uid, "key-created", client_ip(request), {"key": meta["prefix"]})
        return {"key": token, **meta}

    @app.delete("/api/tokens/{tid}")
    def remove_key(tid: str, request: Request, p: Principal = Depends(session_only)):
        with db.tx() as c:
            if not repo.revoke_api_token(c, p.uid, tid):
                raise err(404, "Not found.")
            repo.audit(c, p.uid, "key-revoked", client_ip(request))
        return {"ok": True}

    # ------------------------------------------------------------ documents (the dashboard's data)
    @app.get("/api/c/{col}")
    def list_collection(col: str, request: Request, p: Principal = Depends(principal)):
        check_col(col)
        with db.tx() as c:
            tag = repo.docs_etag(c, p.uid, col)
            if request.headers.get("if-none-match") == tag:
                return Response(status_code=304, headers={"ETag": tag, "Cache-Control": "no-cache"})
            docs = repo.list_docs(c, p.uid, col)
        return JSONResponse({"docs": docs}, headers={"ETag": tag, "Cache-Control": "no-cache"})

    @app.get("/api/d/{col}/{did}")
    def get_document(col: str, did: str, p: Principal = Depends(principal)):
        check_col(col, did)
        with db.tx() as c:
            doc = repo.get_doc(c, p.uid, col, did)
        if not doc:
            raise err(404, "Not found.")
        return doc

    def _validate_body(body) -> dict:
        if not isinstance(body, dict):
            raise err(400, "The document must be a JSON object.", "invalid_argument")
        if len(json.dumps(body)) > cfg.max_doc_kb * 1024:
            raise err(413, "That document is too large.", "too_large")
        return body

    def _after_write(c, uid: str, col: str, did: str) -> None:
        if col == "settings" and did == "profile":
            repo.enqueue(c, "match_user", user_id=uid, dedupe_key=f"match:{uid}", delay_seconds=15, max_attempts=3)

    def _if_version(request: Request) -> int | None:
        v = request.headers.get("if-match", "")
        return int(v) if v.isdigit() else None

    @app.put("/api/d/{col}/{did}")
    def put_document(col: str, did: str, request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        check_col(col, did)
        _validate_body(body)
        with db.tx() as c:
            if not repo.get_doc(c, p.uid, col, did) and repo.count_docs(c, p.uid) >= cfg.max_docs_per_user:
                raise err(400, "Your account has reached its document limit.", "quota")
            try:
                version = repo.set_doc(c, p.uid, col, did, body, _if_version(request))
            except ValueError as e:
                raise err(409, str(e), "conflict") from e
            _after_write(c, p.uid, col, did)
        return {"version": version}

    @app.patch("/api/d/{col}/{did}")
    def patch_document(col: str, did: str, request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        check_col(col, did)
        _validate_body(body)
        with db.tx() as c:
            try:
                version = repo.update_doc(c, p.uid, col, did, body, _if_version(request))
            except KeyError as e:
                raise err(404, "Not found.") from e
            except ValueError as e:
                raise err(409, str(e), "conflict") from e
            _after_write(c, p.uid, col, did)
        return {"version": version}

    @app.delete("/api/d/{col}/{did}")
    def delete_document(col: str, did: str, p: Principal = Depends(session_only)):
        check_col(col, did)
        with db.tx() as c:
            repo.delete_doc(c, p.uid, col, did)
        return {"ok": True}

    # ------------------------------------------------------------ files
    @app.get("/api/assets")
    def assets(p: Principal = Depends(session_only)):
        with db.tx() as c:
            return {"assets": repo.list_assets(c, p.uid), "usage": {"usedBytes": repo.storage_used(c, p.uid),
                                                                     "quotaBytes": cfg.user_storage_mb * 1024 * 1024}}

    @app.post("/api/assets", status_code=201)
    async def upload(request: Request, p: Principal = Depends(principal)):
        cap = cfg.max_upload_mb * 1024 * 1024
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > cap:
                raise err(413, f"Files can be up to {cfg.max_upload_mb} MB.", "too_large")
        data = bytes(data)
        if not data.startswith(b"%PDF-"):
            raise err(415, "Only PDF files can be uploaded.", "unsupported_type")
        name = re.sub(r"[^\w .()-]+", "_", request.query_params.get("name", "resume.pdf"))[:120] or "resume.pdf"

        def save():
            with db.tx() as c:
                if repo.storage_used(c, p.uid) + len(data) > cfg.user_storage_mb * 1024 * 1024:
                    raise err(413, "Your storage is full. Remove an old file first.", "quota")
                aid = security.new_id()
                key = storage.put(p.uid, aid, "pdf", data, conn=c)
                c.execute("INSERT INTO assets(id, user_id, name, content_type, size_bytes, sha256, storage_key, text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (aid, p.uid, name, "application/pdf", len(data), hashlib.sha256(data).hexdigest(), key, pdf_text(data), now_iso()))
                return {"id": aid, "url": f"/_blob/{aid}", "sizeBytes": len(data), "contentType": "application/pdf", "name": name}
        return await run_in_threadpool(save)

    @app.post("/api/read-file")
    async def read_file(request: Request, p: Principal = Depends(principal)):
        """The text of a PDF or Word resume, for filling the Profile. Nothing is stored. Done here because the app's
        security policy doesn't load outside scripts (a PDF reader) in the browser."""
        cap = cfg.max_upload_mb * 1024 * 1024
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > cap:
                raise err(413, f"Files can be up to {cfg.max_upload_mb} MB.", "too_large")
        data = bytes(data)
        with db.tx() as c:
            limited(c, f"read-file:{p.uid}", 30, 3600)
        if data.startswith(b"%PDF-"):
            text = await run_in_threadpool(pdf_text, data)
        elif data.startswith(b"PK"):
            text = await run_in_threadpool(_docx_text, data)
        else:
            raise err(415, "Choose a PDF or Word (.docx) file.", "unsupported_type")
        return {"text": (text or "")[:60000]}

    @app.delete("/api/assets/{aid}")
    def delete_asset(aid: str, p: Principal = Depends(session_only)):
        with db.tx() as c:
            a = repo.get_asset(c, p.uid, aid) if _ASSET_ID.match(aid) else None
            if not a:
                raise err(404, "Not found.")
            c.execute("DELETE FROM assets WHERE id = ? AND user_id = ?", (aid, p.uid))
        storage.delete(a["storage_key"])
        return {"ok": True}

    @app.get("/_blob/{aid}")
    def blob(aid: str, p: Principal = Depends(principal)):
        with db.tx() as c:
            a = repo.get_asset(c, p.uid, aid) if _ASSET_ID.match(aid) else None
        if not a:
            raise err(404, "Not found.")
        safe = re.sub(r'[^\w .()-]', "_", a["name"])
        try:
            data = storage.get(a["storage_key"])
        except FileNotFoundError:
            raise err(404, "This file is no longer stored. Please upload it again.") from None
        return Response(data, media_type=a["content_type"],
                        headers={"Content-Disposition": f'inline; filename="{safe}"', "Cache-Control": "private, no-store"})

    # ------------------------------------------------------------ the user's apply agent
    def _job(c, uid: str, jid: str) -> dict:
        doc = repo.get_doc(c, uid, "jobs", jid) if _DOC_ID.match(jid) else None
        if not doc:
            raise err(404, "Not found.")
        return doc

    def _app_key(d: dict) -> str:
        basis = company_key(d.get("company", "")) + "|" + (canonical_url(d.get("url", "")) or d.get("title", ""))
        return hashlib.sha256(basis.encode()).hexdigest()[:24]

    @app.get("/api/agent/next")
    def agent_next(limit: int = 8, p: Principal = Depends(principal)):
        with db.tx() as c:
            settings = (repo.get_doc(c, p.uid, "settings", "profile") or {"data": {}})["data"]
            jobs = repo.list_docs(c, p.uid, "jobs")
            recent = {r["company_key"] for r in c.all("SELECT company_key FROM applications WHERE user_id = ? AND state = 'submitted' AND updated_at > ?",
                                                      (p.uid, now_iso(timedelta(days=-180))))}
            applicant = repo.get_doc(c, p.uid, "profile", "applicant")
        tz = ZoneInfo(str(settings.get("timezone") or "Asia/Kolkata"))
        today = datetime.now(tz).date()

        def local_day(s):
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(tz).date()
            except (ValueError, AttributeError):
                return None
        with db.tx() as c:
            info = plans.plan_info(cfg, plans.plan_of(c, p.user))
        plan_cap, month_cap = info["autoApplyPerDay"], info["autoApplyPerMonth"]
        cap = min(int(settings.get("dailyCap") or 8), plan_cap)
        done_today = sum(1 for j in jobs if local_day(j["data"].get("appliedAt") or "") == today)
        month = [d for d in (local_day(j["data"].get("appliedAt") or "") for j in jobs if j["data"].get("appliedVia") == "careeros") if d]
        done_month = sum(1 for d in month if (d.year, d.month) == (today.year, today.month))
        recent |= {company_key(j["data"].get("company", "")) for j in jobs if j["data"].get("appliedAt")}
        left = max(0, min(cap - done_today, month_cap - done_month))
        auto = settings.get("approvalMode") == "auto-when-clear"
        order = {"remote-global": 0, "remote-india": 1, "remote-local": 1, "south-india": 2, "local": 2}
        groups = {"queued": [], "approved": [], "auto": []}
        for j in jobs:
            d = j["data"]
            if d.get("appliedAt") or d.get("stage") in ("skipped", "applied", "assessment", "screen", "interview", "offer", "rejected", "withdrawn", "archived") or d.get("needsYou"):
                continue
            if d.get("stage") == "approved":
                groups["queued" if d.get("autoApply") == "queued" else "approved"].append(j)
            elif auto and (d.get("stage") == "ready" or (d.get("stage") in ("found", None, "") and all(ch.get("passed") for ch in d.get("checks") or [{}]))):
                groups["auto"].append(j)

        def key(j):
            d = j["data"]
            try:
                ts = datetime.fromisoformat((d.get("postedAt") or "").replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = 0
            fresh = (time.time() - ts) < 72 * 3600
            return (0 if fresh else 1, order.get(d.get("region", ""), 9), -ts)
        picked, companies = [], set()
        for g, items in (("queued", sorted(groups["queued"], key=lambda j: j["data"].get("queuedAt") or "")),
                         ("approved", sorted(groups["approved"], key=key)), ("auto", sorted(groups["auto"], key=key))):
            for j in items:
                ck = company_key(j["data"].get("company", ""))
                if ck in companies or (g != "queued" and ck in recent):
                    continue
                ok, why = evaluation_mod.apply_gate(j["data"], chosen_by_user=g != "auto")
                if not ok and not why.startswith("Not scored"):
                    continue  # under the apply line without "apply anyway", or a posting that looks unsafe
                companies.add(ck)
                picked.append({"id": j["id"], "version": j["version"], "group": g, **{k: j["data"].get(k) for k in (
                    "company", "title", "url", "region", "postedAt", "location", "workMode", "stage", "checks", "brief", "evidence", "gaps", "score", "scoreOverride")},
                    "needsScore": g == "auto" and not (j["data"].get("evaluation") or {}).get("score")})
        n = min(left, max(0, min(int(limit), 25)))
        res = (applicant or {"data": {}})["data"].get("resume") or {}
        return {"dailyCap": cap, "appliedToday": done_today, "monthCap": month_cap, "appliedThisMonth": done_month, "left": left, "approvalMode": settings.get("approvalMode"), "applyLine": evaluation_mod.APPLY_LINE,
                "paused": settings.get("approvalMode") == "paused", "roles": picked[:n],
                "applicantReady": bool(applicant), "resume": {"id": res.get("id"), "name": res.get("name")} if res.get("id") else None}

    @app.get("/api/agent/applicant")
    def agent_applicant(p: Principal = Depends(principal)):
        with db.tx() as c:
            doc = repo.get_doc(c, p.uid, "profile", "applicant")
            brain = repo.get_doc(c, p.uid, "brain", "brain")
            rid = ((doc or {"data": {}})["data"].get("resume") or {}).get("id", "")
            text = c.scalar("SELECT text FROM assets WHERE id = ? AND user_id = ?", (rid, p.uid)) if rid else None
        return {"applicant": doc["data"] if doc else None, "resumeText": text or "", "brain": brain["data"] if brain else None}

    @app.post("/api/agent/match")
    def agent_match(body: dict = Body(default={}), p: Principal = Depends(principal)):
        """Match score for a posting the extension (or the app) is looking at, against the person's real resume:
        their structured resume, else the text of their uploaded resume, else their Career Brain."""
        from .. import matchscore, scamcheck
        title = re.sub(r"\s+", " ", str(body.get("title") or "")).strip()[:200]
        jd = str(body.get("jd") or "")[:60000]
        if len(jd.strip()) < 80:
            raise err(400, "Open the job's page with its full description to see a match score.", "match")
        with db.tx() as c:
            limited(c, f"match:{p.uid}", 300, 3600)
            prof = (repo.get_doc(c, p.uid, "profile", "resume") or {"data": {}})["data"]
            appl = (repo.get_doc(c, p.uid, "profile", "applicant") or {"data": {}})["data"]
            settings = (repo.get_doc(c, p.uid, "settings", "profile") or {"data": {}})["data"]
            brain = (repo.get_doc(c, p.uid, "brain", "brain") or {"data": {}})["data"]
            rid = (appl.get("resume") or {}).get("id", "")
            text = c.scalar("SELECT text FROM assets WHERE id = ? AND user_id = ?", (rid, p.uid)) if rid else None
        resume, source = matchscore.resume_from_profile(prof), "your Propelo resume"
        if not (resume["bullets"] or resume["skills"] or resume["summary"].strip()):
            if text:
                resume, source = text, "your uploaded resume"
            else:
                resume, source = matchscore.resume_from_brain(brain), "your Career Brain"
        years = settings.get("yearsExperience")
        if years in (None, ""):
            years = appl.get("experienceYears")
        try:
            years = float(years) if years not in (None, "") else None
        except (TypeError, ValueError):
            years = None
        targets = [str(t) for t in (settings.get("targetRoles") or []) if str(t).strip()][:10]
        out = matchscore.score(title, jd, resume, years, targets)
        empty = isinstance(resume, dict) and not (resume["bullets"] or resume["skills"] or resume["summary"].strip())
        return dict(out, source=None if empty else source, needsResume=empty, risk=scamcheck.check({"title": title, "jd": jd}))

    _BIG_BOARDS = re.compile(r"(^|\.)(linkedin\.com|naukri\.com|indeed\.[a-z.]+|wellfound\.com|angel\.co)$", re.I)

    def _posting_extras(body: dict) -> dict:
        """What the extension read from the page's JobPosting data. Posting text is kept as data for scoring;
        it is never treated as instructions."""
        out = {}
        jd = str(body.get("jd") or "").strip()
        if jd:
            out["jd"], out["jdArchivedAt"] = jd[:60000], now_iso()
        for k, n in (("location", 160), ("salary", 120), ("employmentType", 60), ("postedAt", 40), ("validThrough", 40)):
            v = re.sub(r"\s+", " ", str(body.get(k) or "")).strip()[:n]
            if v:
                out[k] = v
        return out

    @app.post("/api/agent/track")
    def agent_track(body: dict = Body(default={}), p: Principal = Depends(principal)):
        """The autofill extension's "Track it": record a role the user applied to (or is about to)
        on a company site. Matches an existing role by company and link, so nothing is tracked twice."""
        url = str(body.get("url", "")).strip()[:600]
        title = re.sub(r"\s+", " ", str(body.get("title", ""))).strip()[:160]
        company = re.sub(r"\s+", " ", str(body.get("company", ""))).strip()[:120]
        applied = body.get("applied") is not False
        if not re.match(r"^https?://", url) or not title or not company:
            raise err(400, "Send the role's link, title and company.", "invalid_argument")
        host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/:]+).*$", r"\1", url).lower())
        d = {"company": company, "title": title, "url": url}
        key = _app_key(d)
        stamp = now_iso()[:19] + "Z"
        with db.tx() as c:
            jobs = repo.list_docs(c, p.uid, "jobs")
            jid_in = str(body.get("jobId") or "")
            # The apply queue sends the role's own id: its form page (a /apply link) differs from the role's link.
            cur = next((j for j in jobs if jid_in and j["id"] == jid_in), None) or next((j for j in jobs if _app_key(j["data"]) == key), None)
            if cur:
                data = cur["data"]
                if applied and not data.get("appliedAt"):
                    repo.update_doc(c, p.uid, "jobs", cur["id"], {"stage": "applied", "appliedAt": stamp, "appliedVia": "you", "needsYou": "",
                                                                    "timeline": repo.append_timeline(data, f"You applied on {host} (tracked by the extension)")})
                return {"id": cur["id"], "created": False, "stage": "applied" if applied else data.get("stage", "found")}
            if repo.count_docs(c, p.uid) >= cfg.max_docs_per_user:
                raise err(400, "Your account has reached its document limit.", "quota")
            jid = "ext-" + key[:16]
            doc = {**d, "source": host, "via": "extension", "stage": "applied" if applied else "found", "foundAt": stamp,
                   "region": "", "checks": [], "timeline": [{"at": stamp, "event": f"Added from {host} by the extension"}]}
            if applied:
                doc.update({"appliedAt": stamp, "appliedVia": "you"})
                doc["timeline"].append({"at": stamp, "event": f"You applied on {host}"})
            if _BIG_BOARDS.search(host):
                doc["note"] = "Tracked from a job board Propelo never fills in."
            doc.update(_posting_extras(body))
            risk = scam_check(doc)
            if risk["level"] != "ok":
                doc["risk"] = risk
            repo.set_doc(c, p.uid, "jobs", jid, doc)
        return {"id": jid, "created": True, "stage": doc["stage"], "risk": doc.get("risk") or {"level": "ok", "reasons": []}}

    @app.post("/api/agent/brain")
    def agent_brain(body: dict = Body(default={}), p: Principal = Depends(principal)):
        brain, status = body.get("brain"), body.get("status") or {}
        if not isinstance(brain, dict) or not isinstance(status, dict):
            raise err(400, "Send {brain: {...}, status: {...}}.", "invalid_argument")
        _validate_body(brain)
        status = {"state": "ready" if status.get("state") == "ready" else "building", "summary": str(status.get("summary", ""))[:400],
                  "counts": status.get("counts") if isinstance(status.get("counts"), dict) else {}, "updatedAt": now_iso()}
        with db.tx() as c:
            repo.set_doc(c, p.uid, "brain", "brain", brain)
            repo.set_doc(c, p.uid, "brain", "status", status)
        return {"ok": True}

    @app.get("/api/prompts/{name}")
    def prompt(name: str, p: Principal = Depends(session_only)):
        if name not in ("apply", "brain"):
            raise err(404, "Not found.")
        text = (Path(__file__).resolve().parent / "prompts" / f"{name}.md").read_text(encoding="utf-8")
        return {"name": name, "text": text.replace("{{SERVER}}", cfg.public_url)}

    @app.post("/api/agent/heartbeat")
    def agent_heartbeat(body: dict = Body(default={}), p: Principal = Depends(principal)):
        patch = {"linked": True, "lastSeenAt": now_iso(), "device": str(body.get("device", ""))[:80], "browser": str(body.get("browser", ""))[:40],
                 "lastError": "", "via": "computer key" if p.kind == "key" else "dashboard"}
        with db.tx() as c:
            if repo.get_doc(c, p.uid, "settings", "applyRunner"):
                repo.update_doc(c, p.uid, "settings", "applyRunner", patch)
            else:
                repo.set_doc(c, p.uid, "settings", "applyRunner", patch)
        return {"ok": True}

    @app.post("/api/agent/jobs/{jid}/fit")
    def agent_fit(jid: str, body: dict = Body(default={}), p: Principal = Depends(principal)):
        """Record the fit check. With "evaluation" (the scored 1-5 evaluation), it is
        checked first: quotes against "jd" (the posting's text, archived on the role),
        claim ids against the brain. A role the user chose that scores under the apply
        line waits for them; it is never submitted on the agent's say-so."""
        allowed = {k: body[k] for k in ("decision", "fitBand", "decisionReason", "evidence", "gaps") if k in body}
        ev = body.get("evaluation")
        if ev is not None and len(json.dumps(ev)) > 96 * 1024:
            raise err(413, "That evaluation is too large.", "too_large")
        jd = str(body.get("jd") or "")[:60000] or None
        with db.tx() as c:
            d = _job(c, p.uid, jid)["data"]
            if ev is not None:
                brain = (repo.get_doc(c, p.uid, "brain", "brain") or {}).get("data")
                errors, warnings = evaluation_mod.validate(ev, jd=jd or d.get("jd"), brain=brain or None)
                if errors:
                    raise HTTPException(422, detail={"error": "The evaluation didn't pass its checks.", "code": "invalid_evaluation", "problems": errors[:20]})
                norm = evaluation_mod.normalize(ev)
                allowed = evaluation_mod.job_patch(norm, ev.get("decision"))
                if jd and not d.get("jd"):
                    allowed["jd"], allowed["jdArchivedAt"] = jd, now_iso()
                event = f"Scored {norm['score']:.1f}/5: {norm['verdict']['label']}"
                if norm["score"] < evaluation_mod.APPLY_LINE and d.get("stage") == "approved" and not d.get("scoreOverride") and not d.get("appliedAt"):
                    allowed.update({"needsYou": f"Scored {norm['score']:.1f}, under the {evaluation_mod.APPLY_LINE} apply line. {norm.get('summary', '')}".strip()[:400],
                                    "needsYouKind": "score", "needsYouAt": now_iso()})
                allowed["timeline"] = repo.append_timeline(d, event)
                version = repo.update_doc(c, p.uid, "jobs", jid, allowed)
                return {"version": version, "score": norm["score"], "verdict": norm["verdict"], "confidence": norm["confidence"],
                        "apply": evaluation_mod.apply_gate(dict(d, **allowed), chosen_by_user=d.get("stage") == "approved")[0], "warnings": warnings}
            return {"version": repo.update_doc(c, p.uid, "jobs", jid, allowed)}

    @app.post("/api/agent/jobs/{jid}/begin")
    def agent_begin(jid: str, body: dict = Body(default={}), p: Principal = Depends(principal)):
        """Call right before pressing Submit. Refuses a second submission, ever.
        Send {"jd": "<the posting's full text>"} to archive it if /fit didn't."""
        with db.tx() as c:
            d = _job(c, p.uid, jid)["data"]
            jd = str((body or {}).get("jd") or "")[:60000]
            if jd and not d.get("jd"):
                repo.update_doc(c, p.uid, "jobs", jid, {"jd": jd, "jdArchivedAt": now_iso()})
            if d.get("appliedAt"):
                raise err(409, "Already applied to this role.", "already_submitted")
            ok, why = evaluation_mod.apply_gate(d, chosen_by_user=d.get("stage") == "approved")
            if not ok:
                raise err(409, why, "below_apply_line" if why.startswith("Scored") else "needs_evaluation")
            key, now = _app_key(d), now_iso()
            row = c.one("SELECT state FROM applications WHERE user_id = ? AND key = ?", (p.uid, key))
            if row and row["state"] == "submitted":
                raise err(409, "Already applied to this role.", "already_submitted")
            if row and row["state"] == "submitting":
                raise err(409, "A previous attempt may have gone through. The user must check before any retry.", "needs_check")
            c.execute("INSERT INTO applications(user_id, key, job_id, company_key, state, attempts, created_at, updated_at) VALUES (?, ?, ?, ?, 'submitting', 1, ?, ?) "
                      "ON CONFLICT (user_id, key) DO UPDATE SET state = 'submitting', attempts = applications.attempts + 1, updated_at = excluded.updated_at",
                      (p.uid, key, jid, company_key(d.get("company", "")), now, now))
        return {"ok": True, "key": key}

    _SENSITIVE_LABEL = re.compile(r"password|otp|one[- ]time|aadhaa?r|\bpan\b|passport|bank|account number|ifsc|date of birth|\bdob\b|cvv|card number", re.I)

    def _receipt_fields(raw) -> list[dict]:
        """The fields auto-apply filled, for the receipt. Sensitive labels are never stored, even if sent."""
        out = []
        for f in (raw if isinstance(raw, list) else [])[:80]:
            if not isinstance(f, dict):
                continue
            label = re.sub(r"\s+", " ", str(f.get("label") or "")).strip()[:160]
            if not label or _SENSITIVE_LABEL.search(label):
                continue
            out.append({"label": label, "value": str(f.get("value") or "")[:300], "source": str(f.get("source") or "")[:40]})
        return out

    @app.post("/api/agent/jobs/{jid}/finish")
    def agent_finish(jid: str, body: dict = Body(default={}), p: Principal = Depends(principal)):
        ok = body.get("confirmed") is True
        with db.tx() as c:
            doc = _job(c, p.uid, jid)
            d = doc["data"]
            key = _app_key(d)
            row = c.one("SELECT state FROM applications WHERE user_id = ? AND key = ?", (p.uid, key))
            if not row or row["state"] != "submitting":
                raise err(409, "Call begin before submitting.", "not_started")
            host = str(body.get("form", ""))[:200]
            if ok:
                receipt = {"confirmation": str(body.get("confirmation", ""))[:500], "form": host, "at": now_iso(), "fields": _receipt_fields(body.get("fields"))}
                if re.match(r"^[A-Za-z0-9_-]{8,64}$", str(body.get("screenshotAsset") or "")):
                    receipt["screenshot"] = str(body["screenshotAsset"])
                c.execute("UPDATE applications SET state = 'submitted', receipt = ?, updated_at = ? WHERE user_id = ? AND key = ?",
                          (json.dumps(receipt), now_iso(), p.uid, key))
                patch = {"stage": "applied", "appliedAt": now_iso()[:19] + "Z", "appliedVia": "careeros", "autoApply": "done", "needsYou": "", "needsYouKind": "",
                         "application": receipt, "timeline": repo.append_timeline(d, f"Applied automatically on {host or 'the company site'}")}
                if body.get("resumeAsset"):
                    patch["resume"] = {"asset": str(body["resumeAsset"])[:40], "label": "Resume sent", "version": str(body.get("resumeVersion", "original"))[:20]}
                for k in ("screening", "coverNote"):
                    if k in body:
                        patch[k] = body[k]
                patch["followUps"] = followups.seed(dict(d, **patch))
            else:
                reason = "Submitted, but no confirmation appeared. Check the site or your email before trying again."
                patch = {"needsYou": reason, "needsYouAt": now_iso(), "autoApply": "done", "applyUrl": str(body.get("applyUrl", d.get("url", "")))[:2000],
                         "timeline": repo.append_timeline(d, "Auto-apply: submitted without a confirmation")}
            version = repo.update_doc(c, p.uid, "jobs", jid, patch)
        return {"ok": True, "version": version}

    @app.post("/api/agent/jobs/{jid}/needs-you")
    def agent_needs_you(jid: str, body: dict = Body(default={}), p: Principal = Depends(principal)):
        reason = str(body.get("reason", "")).strip()[:400]
        if not reason:
            raise err(400, "Say why the role needs the user.", "invalid_argument")
        with db.tx() as c:
            d = _job(c, p.uid, jid)["data"]
            version = repo.update_doc(c, p.uid, "jobs", jid, {
                "needsYou": reason, "needsYouAt": now_iso(), "applyUrl": str(body.get("applyUrl", d.get("url", "")))[:2000],
                "timeline": repo.append_timeline(d, f"Auto-apply stopped: {reason}")})
        return {"ok": True, "version": version}

    @app.post("/api/agent/jobs/{jid}/closed")
    def agent_closed(jid: str, p: Principal = Depends(principal)):
        with db.tx() as c:
            d = _job(c, p.uid, jid)["data"]
            version = repo.update_doc(c, p.uid, "jobs", jid, {"stage": "skipped", "autoApply": "done",
                                                               "skip": {"gate": "Closed", "reason": "The posting is closed.", "wouldChange": ""},
                                                               "timeline": repo.append_timeline(d, "Closed: the posting says it's no longer open")})
        return {"ok": True, "version": version}

    @app.post("/api/agent/runs", status_code=201)
    def agent_run(body: dict = Body(default={}), p: Principal = Depends(principal)):
        doc = {"startedAt": str(body.get("startedAt") or now_iso()), "finishedAt": str(body.get("finishedAt") or now_iso()), "kind": "apply",
               "applied": int(body.get("applied") or 0), "needsYou": int(body.get("needsYou") or 0), "summary": str(body.get("summary", ""))[:500]}
        rid = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S") + "-apply"
        with db.tx() as c:
            repo.set_doc(c, p.uid, "runs", rid, doc)
            if repo.get_doc(c, p.uid, "settings", "applyRunner"):
                repo.update_doc(c, p.uid, "settings", "applyRunner", {"lastRunAt": now_iso(), "lastApplied": doc["applied"]})
        return {"ok": True, "id": rid}

    @app.post("/api/applications/{jid}/reset")
    def reset_application(jid: str, p: Principal = Depends(session_only)):
        """The user checked: an uncertain submission did NOT go through, so auto-apply may try again."""
        with db.tx() as c:
            d = _job(c, p.uid, jid)["data"]
            c.execute("UPDATE applications SET state = 'failed', updated_at = ? WHERE user_id = ? AND key = ? AND state = 'submitting'",
                      (now_iso(), p.uid, _app_key(d)))
        return {"ok": True}

    # ------------------------------------------------------------ plans and billing
    app.state.razorpay = plans.Razorpay(cfg)
    app.state.dodo = plans.Dodo(cfg)

    def provider_for(currency: str):
        return app.state.razorpay if currency == "INR" else app.state.dodo

    @app.get("/api/plans")
    def plan_catalog(request: Request):
        return {"plans": plans.catalog(cfg), "addons": plans.addons(cfg), "checkoutEnabled": cfg.billing_enabled, "currency": guess_currency(request),
                "currencies": {"INR": cfg.razorpay_enabled, "USD": cfg.dodo_enabled}}

    @app.get("/api/billing")
    def billing(p: Principal = Depends(session_only)):
        with db.tx() as c:
            return dict(plans.billing_view(c, cfg, p.user), ai=plans.ai_status(c, cfg, p.user),
                        features=plans.feature_usage(c, cfg, p.uid, plans.plan_of(c, p.user)), **{"pass": passes.view(c, cfg, p.user)})

    @app.post("/api/billing/pass")
    async def buy_pass(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        """Pro for a fixed number of days, paid once. Returns the provider's hosted payment page."""
        currency = str(body.get("currency") or "").upper() or guess_currency(request)
        if currency not in plans.CURRENCIES:
            raise err(400, "Pay in INR or USD.", "bad_currency")
        with db.tx() as c:
            limited(c, f"checkout:{p.uid}", 10, 3600)
            why = "Passes aren't on sale right now." if not cfg.pass_enabled else passes.can_buy(c, p.user)
        if why:
            raise err(409 if cfg.pass_enabled else 503, why, "pass_unavailable")

        def go():
            with db.tx() as c:
                return passes.start(c, cfg, p.user, currency)
        try:
            out = await run_in_threadpool(go)
        except passes.PassError as e:
            raise err(503, str(e), "pass_unavailable")
        except plans.BillingError as e:
            log.warning(json.dumps({"event": "checkout-failed", "provider": "pass", "error": str(e)[:200]}))
            raise err(502, "We couldn't start the payment. Try again in a minute.", "billing")
        with db.tx() as c:
            repo.audit(c, p.uid, "pass-checkout-started", client_ip(request), {"currency": currency})
        return {"url": out["url"]}

    @app.post("/api/billing/checkout")
    async def checkout(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        plan = str(body.get("plan") or "pro").lower()
        currency = str(body.get("currency") or "").upper() or guess_currency(request)
        if plan not in plans.PAID:
            raise err(400, "Pick Pro or Ultra.", "bad_plan")
        if currency not in plans.CURRENCIES:
            raise err(400, "Pay in INR or USD.", "bad_currency")
        provider = provider_for(currency)
        if not provider.offers(plan):
            other = "USD" if currency == "INR" else "INR"
            hint = f" Try paying in {other}." if provider_for(other).offers(plan) else " Write to support and we'll set it up."
            raise err(503, f"Payments in {currency} aren't switched on yet.{hint}", "billing_off")
        with db.tx() as c:
            limited(c, f"checkout:{p.uid}", 10, 3600)
            s = plans.subscription(c, p.uid)
            current = plans.plan_of(c, p.user) if not p.user.get("is_admin") else plans._paid_plan(s)
            if current == plan and not (s and (s["status"] == "cancelled" or s["cancel_at_period_end"])):
                raise err(409, f"You're already on {plan.title()}.", "already_on_plan")
        try:
            sub = await run_in_threadpool(provider.create_subscription, p.uid, p.user["email"], plan)
        except plans.BillingError as e:
            log.warning(json.dumps({"event": "checkout-failed", "provider": provider.name, "error": str(e)[:200]}))
            raise err(502, "We couldn't start the payment. Try again in a minute.", "billing")
        with db.tx() as c:
            plans.start_checkout(c, p.uid, sub, plan, provider.name, currency)
            repo.audit(c, p.uid, "checkout-started", client_ip(request), {"plan": plan, "provider": provider.name, "currency": currency})
        return {"url": sub["url"]}

    @app.post("/api/billing/cancel")
    async def cancel_plan(request: Request, p: Principal = Depends(session_only)):
        with db.tx() as c:
            s = plans.subscription(c, p.uid)
        if not s or s["provider"] not in ("razorpay", "dodo") or s["status"] not in plans.PRO_STATUSES | {"created"}:
            raise err(400, "There's no paid plan to cancel.", "no_subscription")
        client = app.state.razorpay if s["provider"] == "razorpay" else app.state.dodo
        unpaid = s["status"] == "created"
        try:
            if not (unpaid and s["provider"] == "dodo"):  # an unpaid Dodo checkout is only a session: nothing to cancel
                await run_in_threadpool(client.cancel, s["provider_sub_id"], not unpaid)
        except plans.BillingError:
            raise err(502, "We couldn't reach the payment provider. Try again in a minute.", "billing")
        with db.tx() as c:
            if unpaid:
                c.execute("UPDATE subscriptions SET status = 'cancelled', updated_at = ? WHERE user_id = ?", (now_iso(), p.uid))
            else:
                c.execute("UPDATE subscriptions SET cancel_at_period_end = 1, pending_plan = NULL, pending_provider = NULL, "
                          "pending_sub_id = NULL, updated_at = ? WHERE user_id = ?", (now_iso(), p.uid))
            repo.audit(c, p.uid, "plan-cancelled", client_ip(request), {"provider": s["provider"], "plan": s["plan"]})
            return plans.billing_view(c, cfg, p.user)

    @app.post("/api/billing/portal")
    async def billing_portal(request: Request, p: Principal = Depends(session_only)):
        """Dodo's hosted page for invoices and the card on file. Razorpay sends receipts by email."""
        with db.tx() as c:
            limited(c, f"portal:{p.uid}", 20, 3600)
            s = plans.subscription(c, p.uid)
        if not s or s["provider"] != "dodo" or not s["provider_customer_id"]:
            raise err(400, "Invoices for rupee payments arrive by email from Razorpay.", "no_portal")
        try:
            url = await run_in_threadpool(app.state.dodo.portal, s["provider_customer_id"])
        except plans.BillingError:
            raise err(502, "We couldn't reach the payment provider. Try again in a minute.", "billing")
        return {"url": url}

    def record_billing(c, eid: str, ev: dict, event: dict) -> str:
        result, old = plans.apply(c, eid, ev, event)
        row = c.one("SELECT u.id, u.email FROM users u JOIN subscriptions s ON s.user_id = u.id WHERE s.provider_sub_id = ?", (ev["sub_id"],)) \
            if ev["sub_id"] else None
        if old and old.get("sub_id"):
            repo.enqueue(c, "billing_cancel", old, user_id=row["id"] if row else None, dedupe_key=f"bcancel:{old['sub_id']}", max_attempts=8)
        if not row:
            return result
        started = result == "active" and ev["kind"] in ("subscription.activated", "subscription.active")
        if started or old:
            plan = (c.one("SELECT plan FROM subscriptions WHERE user_id = ?", (row["id"],)) or {}).get("plan", "pro")
            send(c, row["email"], mail.pro_welcome(cfg.public_url, plan))
            repo.audit(c, row["id"], "plan-activated", "", {"plan": plan, "provider": ev["provider"]})
        elif result in ("halted", "cancelled", "expired"):
            repo.audit(c, row["id"], f"plan-{result}", "", {"provider": ev["provider"]})
        return result

    @app.post("/api/billing/webhook", include_in_schema=False)
    async def billing_webhook(request: Request):
        """Razorpay."""
        body = await request.body()
        if len(body) > 256_000:
            raise err(413, "Too large.")
        if not plans.verify_signature(body, request.headers.get("x-razorpay-signature", ""), cfg.razorpay_webhook_secret):
            raise err(400, "Bad signature.", "signature")
        try:
            event = json.loads(body)
        except ValueError:
            raise err(400, "Bad JSON.")
        if not isinstance(event, dict):
            raise err(400, "Bad JSON.")
        eid = "rzp:" + (request.headers.get("x-razorpay-event-id") or hashlib.sha256(body).hexdigest())[:100]
        if str(event.get("event", "")) == "payment_link.paid":
            link = (((event.get("payload") or {}).get("payment_link") or {}).get("entity")) or {}
            with db.tx() as c:
                if c.one("SELECT 1 AS x FROM billing_events WHERE id = ?", (eid,)):
                    return {"ok": True, "result": "duplicate"}
                c.execute("INSERT INTO billing_events(id, provider, kind, provider_sub_id, received_at, payload) VALUES (?, 'razorpay', ?, ?, ?, ?)",
                          (eid, "payment_link.paid", str(link.get("id") or "")[:100], now_iso(), json.dumps(event)[:20000]))
                result, g = guarantee.mark_paid(c, cfg, "razorpay", ref=str(link.get("id") or ""), amount=link.get("amount_paid"))
                if result == "unknown":
                    result = concierge.mark_paid(c, str(link.get("id") or ""))
                    if result == "unknown":
                        result, pt = partners.mark_paid(c, "razorpay", ref=str(link.get("id") or ""), amount=link.get("amount_paid"))
                        if result == "paid":
                            for to in partners.admin_emails(c, pt["id"]):
                                send(c, to, mail.business(cfg.public_url, "paid", pt["name"]))
                        elif result == "unknown":
                            result, ps = passes.mark_paid(c, cfg, "razorpay", ref=str(link.get("id") or ""), amount=link.get("amount_paid"))
                            if result == "paid":
                                u = c.one("SELECT email FROM users WHERE id = ?", (ps["user_id"],))
                                if u:
                                    send(c, u["email"], mail.pass_started(cfg.public_url, ps["days"], ps["ends_at"]))
                elif result == "paid":
                    u = c.one("SELECT email FROM users WHERE id = ?", (g["user_id"],))
                    if u:
                        send(c, u["email"], mail.guarantee(cfg.public_url, g["kind"], "enrolled"))
            log.info(json.dumps({"event": "billing-webhook", "provider": "razorpay", "kind": "payment_link.paid", "result": result}))
            return {"ok": True, "result": result}
        ev = plans.razorpay_event(cfg, event)
        with db.tx() as c:
            result = record_billing(c, eid, ev, event)
        log.info(json.dumps({"event": "billing-webhook", "provider": "razorpay", "kind": ev["kind"][:60], "result": result}))
        return {"ok": True, "result": result}

    @app.post("/api/billing/dodo-webhook", include_in_schema=False)
    async def dodo_webhook(request: Request):
        """Dodo Payments (Standard Webhooks)."""
        body = await request.body()
        if len(body) > 256_000:
            raise err(413, "Too large.")
        headers = {k: request.headers.get(k, "") for k in ("webhook-id", "webhook-timestamp", "webhook-signature")}
        if not plans.verify_standard_webhook(body, headers, cfg.dodo_webhook_secret):
            raise err(400, "Bad signature.", "signature")
        try:
            event = json.loads(body)
        except ValueError:
            raise err(400, "Bad JSON.")
        if not isinstance(event, dict):
            raise err(400, "Bad JSON.")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        if str(event.get("type", "")).startswith("payment.") and meta.get("guarantee_id"):
            # A guarantee add-on bought in dollars.
            eid = "dodo:" + headers["webhook-id"][:100]
            with db.tx() as c:
                if c.one("SELECT 1 AS x FROM billing_events WHERE id = ?", (eid,)):
                    return {"ok": True, "result": "duplicate"}
                c.execute("INSERT INTO billing_events(id, provider, kind, provider_sub_id, received_at, payload) VALUES (?, 'dodo', ?, ?, ?, ?)",
                          (eid, str(event.get("type"))[:60], str(data.get("payment_id") or "")[:100], now_iso(), json.dumps(event)[:20000]))
                result = "ignored"
                if event.get("type") == "payment.succeeded":
                    result, g = guarantee.mark_paid(c, cfg, "dodo", guarantee_id=str(meta.get("guarantee_id"))[:64], amount=data.get("total_amount"))
                    if result == "paid":
                        u = c.one("SELECT email FROM users WHERE id = ?", (g["user_id"],))
                        if u:
                            send(c, u["email"], mail.guarantee(cfg.public_url, g["kind"], "enrolled"))
            log.info(json.dumps({"event": "billing-webhook", "provider": "dodo", "kind": "guarantee-" + str(event.get("type"))[:40], "result": result}))
            return {"ok": True, "result": result}
        if str(event.get("type", "")).startswith("payment.") and meta.get("pass_id"):
            # A pass bought in dollars.
            eid = "dodo:" + headers["webhook-id"][:100]
            with db.tx() as c:
                if c.one("SELECT 1 AS x FROM billing_events WHERE id = ?", (eid,)):
                    return {"ok": True, "result": "duplicate"}
                c.execute("INSERT INTO billing_events(id, provider, kind, provider_sub_id, received_at, payload) VALUES (?, 'dodo', ?, ?, ?, ?)",
                          (eid, str(event.get("type"))[:60], str(data.get("payment_id") or "")[:100], now_iso(), json.dumps(event)[:20000]))
                result = "ignored"
                if event.get("type") == "payment.succeeded":
                    result, ps = passes.mark_paid(c, cfg, "dodo", pass_id=str(meta.get("pass_id"))[:64], amount=data.get("total_amount"))
                    if result == "paid":
                        u = c.one("SELECT email FROM users WHERE id = ?", (ps["user_id"],))
                        if u:
                            send(c, u["email"], mail.pass_started(cfg.public_url, ps["days"], ps["ends_at"]))
            log.info(json.dumps({"event": "billing-webhook", "provider": "dodo", "kind": "pass-" + str(event.get("type"))[:40], "result": result}))
            return {"ok": True, "result": result}
        if str(event.get("type", "")).startswith("payment.") and meta.get("partner_payment_id"):
            # A business account bought in dollars.
            eid = "dodo:" + headers["webhook-id"][:100]
            with db.tx() as c:
                if c.one("SELECT 1 AS x FROM billing_events WHERE id = ?", (eid,)):
                    return {"ok": True, "result": "duplicate"}
                c.execute("INSERT INTO billing_events(id, provider, kind, provider_sub_id, received_at, payload) VALUES (?, 'dodo', ?, ?, ?, ?)",
                          (eid, str(event.get("type"))[:60], str(data.get("payment_id") or "")[:100], now_iso(), json.dumps(event)[:20000]))
                result = "ignored"
                if event.get("type") == "payment.succeeded":
                    result, pt = partners.mark_paid(c, "dodo", payment_id=str(meta.get("partner_payment_id"))[:64], amount=data.get("total_amount"))
                    if result == "paid":
                        for to in partners.admin_emails(c, pt["id"]):
                            send(c, to, mail.business(cfg.public_url, "paid", pt["name"]))
            log.info(json.dumps({"event": "billing-webhook", "provider": "dodo", "kind": "business-" + str(event.get("type"))[:40], "result": result}))
            return {"ok": True, "result": result}
        ev = plans.dodo_event(cfg, event)
        with db.tx() as c:
            result = record_billing(c, "dodo:" + headers["webhook-id"][:100], ev, event)
        log.info(json.dumps({"event": "billing-webhook", "provider": "dodo", "kind": ev["kind"][:60], "result": result}))
        return {"ok": True, "result": result}

    # ------------------------------------------------------------ recruiter emails from the person's Gmail
    GM_STATE = "propelo_gm_state"

    def gm_redirect_uri() -> str:
        return f"{cfg.public_url}/api/mailbox/google/callback"

    @app.get("/api/autosend")
    def autosend_view(p: Principal = Depends(session_only)):
        with db.tx() as c:
            return autosend.view(c, cfg, p.user)

    @app.get("/api/mailbox/google/start")
    def mailbox_start(p: Principal = Depends(session_only)):
        if not cfg.gmail_enabled:
            raise err(404, "Sending from Gmail isn't set up on this server.", "not_configured")
        state = secrets.token_urlsafe(24)
        resp = RedirectResponse(mailbox.authorize_url(cfg.google_client_id, gm_redirect_uri(), state, p.user["email"]), status_code=303)
        resp.set_cookie(GM_STATE, f"{state}.{p.uid}", max_age=600, httponly=True, secure=cfg.secure_cookies, samesite="lax", path="/api/mailbox/google")
        return resp

    @app.get("/api/mailbox/google/callback")
    def mailbox_callback(request: Request, code: str = "", state: str = "", error: str = "", p: Principal = Depends(session_only)):
        def back(msg: str):
            resp = RedirectResponse(f"/app?mail={msg}#outreach", status_code=303)
            resp.delete_cookie(GM_STATE, path="/api/mailbox/google")
            return resp
        if not cfg.gmail_enabled:
            raise err(404, "Sending from Gmail isn't set up on this server.", "not_configured")
        expected = request.cookies.get(GM_STATE, "")
        if error or not code or not expected or not secrets.compare_digest(expected, f"{state}.{p.uid}"):
            return back("cancelled" if error else "state")
        with db.tx() as c:
            limited(c, f"gmail:{p.uid}", 10, 3600)
        try:
            got = mailbox.exchange(code, gm_redirect_uri(), cfg.google_client_id, cfg.google_client_secret)
        except mailbox.MailError as e:
            log.warning(json.dumps({"event": "gmail-connect-failed", "error": str(e)[:200]}))
            return back("failed")
        with db.tx() as c:
            autosend.save_mailbox(c, cfg, p.uid, got["address"], got["refresh_token"])
            repo.audit(c, p.uid, "gmail-connected", client_ip(request))
        return back("connected")

    @app.delete("/api/mailbox")
    async def mailbox_remove(request: Request, p: Principal = Depends(session_only)):
        with db.tx() as c:
            row = autosend.mailbox_row(c, p.uid)
        if row:
            try:
                await run_in_threadpool(mailbox.revoke, autosend.refresh_token(cfg, row))
            except Exception:  # noqa: BLE001 - unreadable or already revoked: removing it here is what matters
                pass
        with db.tx() as c:
            c.execute("DELETE FROM mailboxes WHERE user_id = ?", (p.uid,))
            c.execute("UPDATE outreach_sends SET status = 'cancelled', error = 'Gmail was disconnected.' WHERE user_id = ? AND status = 'queued'", (p.uid,))
            repo.audit(c, p.uid, "gmail-disconnected", client_ip(request))
            return autosend.view(c, cfg, p.user)

    @app.post("/api/autosend/{sid}/cancel")
    def autosend_cancel(sid: str, p: Principal = Depends(session_only)):
        with db.tx() as c:
            n = c.execute("UPDATE outreach_sends SET status = 'cancelled', error = 'Cancelled by you.' WHERE id = ? AND user_id = ? AND status = 'queued'",
                          (sid, p.uid)).rowcount
            if not n:
                raise err(404, "That email isn't waiting to be sent.")
            return autosend.view(c, cfg, p.user)

    @app.post("/api/autosend/stop/{jid}")
    def autosend_stop(jid: str, p: Principal = Depends(session_only)):
        """No more automatic emails about this role: cancels anything queued and stops follow-ups."""
        check_col("jobs", jid)
        with db.tx() as c:
            d = _job(c, p.uid, jid)["data"]
            c.execute("UPDATE outreach_sends SET status = 'cancelled', error = 'Stopped by you.' WHERE user_id = ? AND job_id = ? AND status = 'queued'", (p.uid, jid))
            o = dict(d.get("outreach") or {})
            repo.update_doc(c, p.uid, "jobs", jid, {"outreach": dict(o, stopped=True),
                                                     "timeline": repo.append_timeline(d, "Automatic emails stopped for this role")})
            return autosend.view(c, cfg, p.user)

    @app.get("/optout", include_in_schema=False)
    def optout_page(request: Request, a: str = "", s: str = ""):
        addr = autosend.read_optout(cfg, a, s)
        nonce = request.state.nonce
        if not addr:
            body = "<h1>This link isn't valid</h1><p>Reply \"stop\" to the email instead, and the sender will see it.</p>"
        else:
            body = (f"<h1>Stop emails from Propelo users</h1><p>Emails sent with Propelo will no longer go to <b>{html_escape(addr)}</b>, from anyone.</p>"
                    f'<form method="post" action="/optout?a={html_escape(a)}&amp;s={html_escape(s)}"><button type="submit">Stop these emails</button></form>')
        page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>Propelo email preferences</title><style>body{font:17px/1.6 system-ui,sans-serif;background:#FAF3E6;color:#151515;max-width:560px;margin:12vh auto;padding:0 20px}'
                'h1{font-weight:500;letter-spacing:-.02em}button{font:inherit;background:#151515;color:#FAF3E6;border:0;border-radius:999px;padding:12px 22px;cursor:pointer}</style></head>'
                f"<body>{body}</body></html>")
        return HTMLResponse(page.replace("<script>", f'<script nonce="{nonce}">'))

    @app.post("/optout", include_in_schema=False)
    def optout_post(request: Request, a: str = "", s: str = ""):
        """The page's button, and mail apps' one-click unsubscribe (RFC 8058)."""
        addr = autosend.read_optout(cfg, a, s)
        if not addr:
            raise err(400, "This link isn't valid.")
        with db.tx() as c:
            limited(c, "optout:" + security.ip_key(client_ip(request)), 60, 3600)
            autosend.opt_out(c, addr)
        if "text/html" in request.headers.get("accept", ""):
            return HTMLResponse('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                                '<title>Done</title><body style="font:17px/1.6 system-ui,sans-serif;background:#FAF3E6;max-width:560px;margin:12vh auto;padding:0 20px">'
                                '<h1 style="font-weight:500">Done</h1><p>You won\'t get emails sent with Propelo at this address again.</p></body>')
        return {"ok": True}

    # ------------------------------------------------------------ business accounts (consultancies and agencies)
    def perr(e: partners.PartnerError):
        return err(404 if str(e) == "Not found." else 400, str(e), "partner")

    def own_partner(c, pid: str, p: Principal) -> dict:
        ps = [x for x in partners.admin_partners(c, p.uid) if x["id"] == pid]
        if not ps and not (p.user["is_admin"] or p.user.get("is_staff")):
            raise err(404, "Not found.")
        found = ps[0] if ps else partners.get(c, pid)
        if not found:
            raise err(404, "Not found.")
        return found

    @app.get("/join/{code}", include_in_schema=False)
    def join_page(request: Request, code: str):
        return html("join.html", request.state.nonce)

    @app.get("/partner", include_in_schema=False)
    def partner_page(request: Request):
        if not request.cookies.get(COOKIE):
            return RedirectResponse("/login?next=/partner", status_code=303)
        return html("partner.html", request.state.nonce)

    @app.get("/api/join/{code}")
    def join_info(code: str):
        with db.tx() as c:
            pt = partners.by_code(c, code)
            if not pt or pt["kind"] != "consultancy":
                raise err(404, "This invite link isn't valid.")
            left = int(pt["seats"] or 0) - partners.seats_used(c, pt["id"])
        return {**partners.branding(pt), "open": partners.is_live(pt) and left > 0,
                "consent": partners.CONSENT.format(name=pt["name"]), "plan": pt["student_plan"]}

    @app.get("/api/partner-logo/{slug}")
    def partner_logo(slug: str):
        with db.tx() as c:
            got = partners.logo_bytes(partners.by_slug(c, slug))
        if not got:
            raise err(404, "Not found.")
        return Response(got[0], media_type=got[1], headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/partner/join")
    def partner_join(body: dict = Body(...), p: Principal = Depends(session_only)):
        try:
            with db.tx() as c:
                limited(c, f"pjoin:{p.uid}", 20, 3600)
                pt = partners.join(c, str(body.get("code") or ""), p.uid, body.get("consent") is True)
                repo.audit(c, p.uid, "partner.join", detail={"partner": pt["id"]})
                return {"ok": True, "partner": partners.branding(pt)}
        except partners.PartnerError as e:
            raise perr(e)

    @app.post("/api/partner/leave")
    def partner_leave(p: Principal = Depends(session_only)):
        with db.tx() as c:
            partners.leave(c, p.uid)
        return {"ok": True}

    @app.get("/api/partner")
    def partner_view(p: Principal = Depends(session_only)):
        with db.tx() as c:
            return {"partners": [partners.view(c, x, cfg.public_url) for x in partners.admin_partners(c, p.uid)],
                    "student": partners.branding(partners.student_of(c, p.uid))}

    @app.patch("/api/partner/{pid}")
    def partner_update(pid: str, body: dict = Body(...), p: Principal = Depends(session_only)):
        try:
            with db.tx() as c:
                own_partner(c, pid, p)
                changes = {k: body[k] for k in ("brand", "filters") if k in body}
                pt = partners.update(c, pid, changes)
                return partners.view(c, pt, cfg.public_url)
        except partners.PartnerError as e:
            raise perr(e)

    @app.post("/api/partner/{pid}/logo")
    def partner_set_logo(pid: str, body: dict = Body(...), p: Principal = Depends(session_only)):
        try:
            with db.tx() as c:
                own_partner(c, pid, p)
                partners.set_logo(c, pid, body.get("dataUrl") or None)
                return partners.view(c, partners.get(c, pid), cfg.public_url)
        except partners.PartnerError as e:
            raise perr(e)

    @app.post("/api/partner/{pid}/rotate-invite")
    def partner_rotate_invite(pid: str, p: Principal = Depends(session_only)):
        with db.tx() as c:
            own_partner(c, pid, p)
            partners.rotate_code(c, pid)
            return partners.view(c, partners.get(c, pid), cfg.public_url)

    @app.post("/api/partner/{pid}/rotate-key")
    def partner_rotate_key(pid: str, p: Principal = Depends(session_only)):
        with db.tx() as c:
            pt = own_partner(c, pid, p)
            if pt["kind"] != "agency":
                raise err(400, "Only agency accounts have a feed key.")
            return {"key": partners.rotate_key(c, pid)}

    @app.post("/api/partner/{pid}/remove/{uid}")
    def partner_remove(pid: str, uid: str, p: Principal = Depends(session_only)):
        with db.tx() as c:
            own_partner(c, pid, p)
            partners.remove(c, pid, uid)
            return partners.view(c, partners.get(c, pid), cfg.public_url)

    @app.get("/api/partner/{pid}/preview")
    def partner_preview(pid: str, p: Principal = Depends(session_only)):
        """The first 50 rows of an agency's feed with its current filters, for the settings page."""
        with db.tx() as c:
            pt = own_partner(c, pid, p)
            if pt["kind"] != "agency":
                raise err(400, "Only agency accounts have a feed.")
            rows = partners.feed_rows(c, {**pt["filters"], "limit": 50})
        return {"rows": rows, "columns": partners.FEED_COLUMNS}

    @app.get("/api/partner-feed/{name}")
    def partner_feed(name: str, request: Request, key: str = ""):
        m = re.fullmatch(r"([a-z0-9-]{1,60})\.(csv|json)", name)
        if not m:
            raise err(404, "Not found.")
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else key
        with db.tx() as c:
            pt = partners.by_key(c, token)
            if not pt or pt["slug"] != m.group(1):
                raise err(401, "Wrong or missing feed key.", "unauthenticated")
            if not partners.is_live(pt):
                raise err(403, "This feed is paused. Contact us to switch it back on.", "paused")
            limited(c, f"pfeed:{pt['id']}", 120, 3600)
            rows = partners.feed_rows(c, pt["filters"])
            gen = feed_state(c).get("generatedAt")
        headers = {"Cache-Control": "private, max-age=300", "X-Feed-Generated-At": str(gen or "")}
        if m.group(2) == "json":
            return JSONResponse({"generatedAt": gen, "partner": pt["name"], "count": len(rows), "roles": rows}, headers=headers)
        headers["Content-Disposition"] = f'attachment; filename="{pt["slug"]}-roles.csv"'
        return Response(partners.to_csv(rows), media_type="text/csv; charset=utf-8", headers=headers)

    @app.get("/business", include_in_schema=False)
    def business_page(request: Request):
        return html("business.html", request.state.nonce, canonical="/business")

    @app.get("/api/business/plans")
    def business_plans(request: Request):
        return partners.catalog(cfg, guess_currency(request))

    @app.post("/api/business/start")
    def business_start(request: Request, body: dict = Body(...), p: Principal = Depends(session_only)):
        pilot = body.get("pilot") is True
        if body.get("agree") is not True:
            raise err(400, "Read and accept the business terms first.", "terms")
        try:
            with db.tx() as c:
                limited(c, f"bstart:{p.uid}", 10, 3600)
                pt = partners.start(c, p.user, str(body.get("plan") or ""), str(body.get("name") or ""), body.get("details") or {},
                                    str(body.get("currency") or guess_currency(request)), pilot)
                repo.audit(c, p.uid, "business.pilot-request" if pilot else "business.start", client_ip(request), {"partner": pt["id"], "plan": pt.get("plan")})
                if pilot:
                    send(c, p.user["email"], mail.business(cfg.public_url, "requested", pt["name"]))
                    for to in staff_emails(c):
                        send(c, to, mail.business(cfg.public_url, "staff-requested", pt["name"]))
                    return {"partner": partners.view(c, pt, cfg.public_url)}
                got = partners.checkout(c, cfg, p.user, pt)
                return {"partner": partners.view(c, partners.get(c, pt["id"]), cfg.public_url), "url": got["url"]}
        except partners.PartnerError as e:
            raise perr(e)
        except plans.BillingError as e:
            log.warning(json.dumps({"event": "business-checkout-failed", "error": str(e)[:300]}))
            raise err(502, "We couldn't start the payment just now. Try again in a minute, or write to us and we'll send a payment link.", "billing")

    @app.post("/api/partner/{pid}/pay")
    def partner_pay(pid: str, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        try:
            with db.tx() as c:
                pt = own_partner(c, pid, p)
                plan = str(body.get("plan") or pt.get("plan") or "")
                if plan not in partners.BUSINESS_PLANS or partners.BUSINESS_PLANS[plan]["kind"] != pt["kind"]:
                    raise partners.PartnerError("Choose a plan for this kind of account.")
                cur = str(body.get("currency") or pt.get("currency") or "INR")
                c.execute("UPDATE partners SET plan = ?, currency = ?, updated_at = ? WHERE id = ?", (plan, cur if cur in ("INR", "USD") else "INR", now_iso(), pid))
                got = partners.checkout(c, cfg, p.user, partners.get(c, pid))
                return {"url": got["url"]}
        except partners.PartnerError as e:
            raise perr(e)
        except plans.BillingError as e:
            log.warning(json.dumps({"event": "business-checkout-failed", "error": str(e)[:300]}))
            raise err(502, "We couldn't start the payment just now. Try again in a minute, or write to us and we'll send a payment link.", "billing")

    @app.post("/api/staff/partners/{pid}/approve-pilot")
    def staff_partner_pilot(pid: str, p: Principal = Depends(staff_only)):
        try:
            with db.tx() as c:
                pt = partners.approve_pilot(c, pid)
                for to in partners.admin_emails(c, pid):
                    send(c, to, mail.business(cfg.public_url, "pilot", pt["name"]))
                return {"partner": partners.staff_row(c, pt)}
        except partners.PartnerError as e:
            raise perr(e)

    @app.get("/api/staff/partners")
    def staff_partners(p: Principal = Depends(staff_only)):
        with db.tx() as c:
            rows = [partners._load(r) for r in c.all("SELECT * FROM partners ORDER BY created_at DESC LIMIT 500")]
            return {"partners": [partners.staff_row(c, x) for x in rows]}

    @app.post("/api/staff/partners", status_code=201)
    def staff_partner_create(body: dict = Body(...), p: Principal = Depends(staff_only)):
        email = str(body.get("adminEmail") or "").strip().lower()
        try:
            with db.tx() as c:
                admin = c.one("SELECT id FROM users WHERE email = ?", (email,)) if email else None
                if email and not admin:
                    raise partners.PartnerError("No account with that email. Ask them to sign up first, then add them.")
                pt, key = partners.create(c, str(body.get("kind") or ""), str(body.get("name") or ""), p.uid,
                                          seats=int(body.get("seats") or 0), status=str(body.get("status") or "pilot"),
                                          ends_at=body.get("endsAt") or None, brand=body.get("brand") or {}, filters=body.get("filters") or {},
                                          billing=body.get("billing") or {}, student_plan=str(body.get("studentPlan") or "pro"))
                if admin:
                    partners.add_admin(c, pt["id"], admin["id"])
                return {"partner": partners.staff_row(c, pt), "feedKey": key}
        except (partners.PartnerError, ValueError) as e:
            raise err(400, str(e), "partner")

    @app.patch("/api/staff/partners/{pid}")
    def staff_partner_update(pid: str, body: dict = Body(...), p: Principal = Depends(staff_only)):
        try:
            with db.tx() as c:
                pt = partners.update(c, pid, body)
                email = str(body.get("addAdmin") or "").strip().lower()
                if email:
                    u = c.one("SELECT id FROM users WHERE email = ?", (email,))
                    if not u:
                        raise partners.PartnerError("No account with that email.")
                    partners.add_admin(c, pid, u["id"])
                return {"partner": partners.staff_row(c, pt)}
        except (partners.PartnerError, ValueError) as e:
            raise perr(partners.PartnerError(str(e)))

    @app.post("/api/staff/partners/{pid}/rotate-key")
    def staff_partner_key(pid: str, p: Principal = Depends(staff_only)):
        with db.tx() as c:
            pt = partners.get(c, pid)
            if not pt or pt["kind"] != "agency":
                raise err(404, "Not found.")
            return {"key": partners.rotate_key(c, pid)}

    # ------------------------------------------------------------ Concierge (human-run search, fee only after joining)
    def cerr(e: concierge.ConciergeError):
        return err(404 if str(e) == "Not found." else 400, str(e), "concierge")

    def staff_emails(c) -> list[str]:
        return [r["email"] for r in c.all("SELECT email FROM users WHERE (is_staff = 1 OR is_admin = 1) AND disabled_at IS NULL LIMIT 20")]

    @app.get("/api/concierge")
    def concierge_view(request: Request, p: Principal = Depends(session_only)):
        with db.tx() as c:
            return concierge.view(c, cfg, p.user, request.headers.get("cf-ipcountry", ""))

    @app.get("/api/concierge/fee")
    def concierge_fee(ctc: int = 0):
        if not cfg.concierge_enabled:
            raise err(404, "Not found.")
        return concierge.fee_for(cfg, max(0, min(int(ctc), 1_000_000_000)))

    @app.post("/api/concierge/request")
    def concierge_request(request: Request, body: dict = Body(...), p: Principal = Depends(session_only)):
        if body.get("agree") is not True or body.get("termsVersion") != concierge.TERMS_VERSION:
            raise err(400, "Read and accept the Concierge terms first.", "terms")
        try:
            intake = concierge.clean_intake(body.get("intake") or {})
            with db.tx() as c:
                limited(c, f"concierge:{p.uid}", 5, 86400)
                concierge.request(c, cfg, p.uid, str(body.get("country") or ""), intake, client_ip(request), p.user)
                send(c, p.user["email"], mail.concierge(cfg.public_url, "requested"))
                for to in staff_emails(c):
                    send(c, to, mail.concierge(cfg.public_url, "staff-new"))
                return concierge.view(c, cfg, p.user)
        except concierge.ConciergeError as e:
            raise cerr(e)

    @app.post("/api/concierge/roles/{sid}/{decision}")
    def concierge_decide(sid: str, decision: str, p: Principal = Depends(session_only)):
        if decision not in ("approve", "decline"):
            raise err(404, "Not found.")
        try:
            with db.tx() as c:
                concierge.decide(c, p.uid, sid, decision == "approve")
                return concierge.view(c, cfg, p.user)
        except concierge.ConciergeError as e:
            raise cerr(e)

    @app.post("/api/concierge/message")
    def concierge_message(body: dict = Body(...), p: Principal = Depends(session_only)):
        try:
            with db.tx() as c:
                limited(c, f"cmsg:{p.uid}", 60, 3600)
                case = concierge.case_of(c, p.uid)
                if not case or case["status"] not in concierge.OPEN_CASE:
                    raise concierge.ConciergeError("You don't have an open Concierge case.")
                concierge.add_note(c, case["id"], p.uid, str(body.get("body") or ""))
                partner = c.one("SELECT email FROM users WHERE id = ?", (case["partner_id"],)) if case["partner_id"] else None
                for to in ([partner["email"]] if partner else staff_emails(c)):
                    send(c, to, mail.concierge(cfg.public_url, "staff-message"))
                return concierge.view(c, cfg, p.user)
        except concierge.ConciergeError as e:
            raise cerr(e)

    @app.post("/api/concierge/offer")
    def concierge_offer(body: dict = Body(...), p: Principal = Depends(session_only)):
        try:
            ctc = int(float(str(body.get("fixedCtc") or 0).replace(",", "")))
        except ValueError:
            raise err(400, "The fixed pay must be a number.")
        try:
            with db.tx() as c:
                r = concierge.report_offer(c, cfg, p.uid, str(body.get("company") or ""), ctc, str(body.get("joiningDate") or ""),
                                           str(body.get("offerDoc") or ""))
                for to in staff_emails(c):
                    send(c, to, mail.concierge(cfg.public_url, "staff-message"))
                return dict(concierge.view(c, cfg, p.user), reported=r)
        except concierge.ConciergeError as e:
            raise cerr(e)

    @app.post("/api/concierge/pause")
    def concierge_pause(body: dict = Body(default={}), p: Principal = Depends(session_only)):
        with db.tx() as c:
            case = concierge.case_of(c, p.uid)
            if not case or case["status"] not in ("active", "paused", "requested"):
                raise err(400, "There's no case to pause or resume.")
            new = "paused" if body.get("pause", True) else ("active" if case["partner_id"] else "requested")
            if new != "paused" and not concierge.plan_allows(c, p.user):
                raise err(402, "Concierge is part of Pro and Ultra. Upgrade in Settings to resume.", "plan_required")
            concierge.set_status(c, case["id"], new)
            repo.audit(c, p.uid, f"concierge-{new}", "")
            return concierge.view(c, cfg, p.user)

    @app.post("/api/concierge/close")
    def concierge_close(p: Principal = Depends(session_only)):
        """Stop Concierge. Fees still apply to offers from roles approved before closing, within the attribution window."""
        with db.tx() as c:
            case = concierge.case_of(c, p.uid)
            if not case or case["status"] not in concierge.OPEN_CASE:
                raise err(400, "There's no open case.")
            concierge.set_status(c, case["id"], "closed", "Closed by the candidate.")
            c.execute("UPDATE concierge_submissions SET status = 'withdrawn', updated_at = ? WHERE case_id = ? AND status = 'proposed'", (now_iso(), case["id"]))
            repo.audit(c, p.uid, "concierge-closed", "")
            return concierge.view(c, cfg, p.user)

    @app.post("/api/concierge/instalments/{iid}/pay")
    async def concierge_pay(iid: str, p: Principal = Depends(session_only)):
        with db.tx() as c:
            inst = c.one("SELECT i.*, pl.company FROM concierge_instalments i JOIN concierge_placements pl ON pl.id = i.placement_id "
                         "JOIN concierge_cases k ON k.id = pl.case_id WHERE i.id = ? AND k.user_id = ?", (iid, p.uid))
        if not inst or inst["status"] not in ("due", "link_sent"):
            raise err(404, "Nothing to pay here.")
        if inst["link_url"]:
            return {"url": inst["link_url"]}
        try:
            link = await run_in_threadpool(concierge.payment_link, cfg, inst, p.user, inst["company"])
        except (concierge.ConciergeError, plans.BillingError) as e:
            raise err(502, str(e), "billing")
        with db.tx() as c:
            c.execute("UPDATE concierge_instalments SET status = 'link_sent', provider_link_id = ?, link_url = ? WHERE id = ?", (link["id"], link["url"], iid))
            repo.audit(c, p.uid, "concierge-payment-link", "", {"instalment": iid})
        return {"url": link["url"]}

    # The team's workspace
    # ------------------------------------------------------------ Guarantees (money back, never a promised job)
    def gerr(e: guarantee.GuaranteeError):
        return err(404 if str(e) == "Not found." else 400, str(e), "guarantee")

    @app.get("/api/guarantee")
    def guarantee_view(p: Principal = Depends(session_only)):
        with db.tx() as c:
            return guarantee.view(c, cfg, p.user)

    @app.post("/api/guarantee/interview/apply")
    def guarantee_apply(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        """Apply for the Interview Guarantee (Pro and Ultra). The team reviews it; payment comes only after acceptance."""
        if body.get("agree") is not True or body.get("termsVersion") != guarantee.TERMS_VERSION:
            raise err(400, "Read and accept the guarantee terms first.", "guarantee")
        try:
            with db.tx() as c:
                limited(c, f"guarantee:{p.uid}", 10, 86400)
                guarantee.apply(c, cfg, p.user, {"roles": body.get("roles"), "note": body.get("note")}, client_ip(request))
                send(c, p.user["email"], mail.guarantee(cfg.public_url, "interview", "applied"))
                for to in staff_emails(c):
                    send(c, to, mail.guarantee(cfg.public_url, "interview", "staff-applied"))
                return guarantee.view(c, cfg, p.user)
        except guarantee.GuaranteeError as e:
            raise gerr(e) from None

    @app.post("/api/guarantee/{kind}/buy")
    def guarantee_buy(kind: str, request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        """Buy a guarantee add-on (Pro and Ultra only): returns the payment page. It starts when the payment goes through."""
        if body.get("agree") is not True or body.get("termsVersion") != guarantee.TERMS_VERSION:
            raise err(400, "Read and accept the guarantee terms first.", "guarantee")
        try:
            with db.tx() as c:
                limited(c, f"guarantee:{p.uid}", 10, 86400)
                g = guarantee.buy(c, cfg, p.user, kind, client_ip(request))
                return dict(guarantee.view(c, cfg, p.user), payUrl=g.get("pay_url"))
        except guarantee.GuaranteeError as e:
            raise gerr(e) from None
        except plans.BillingError as e:
            log.warning(json.dumps({"event": "guarantee-checkout-failed", "error": str(e)[:300]}))
            raise err(502, "We couldn't start the payment just now. Try again in a minute, or write to us and we'll send a payment link.", "billing") from None

    @app.post("/api/admin/guarantee")
    def admin_guarantee(body: dict = Body(...), p: Principal = Depends(admin_only)):
        """Start a guarantee for someone without payment (goodwill or testing). They must still be eligible."""
        try:
            with db.tx() as c:
                u = c.one("SELECT id, email FROM users WHERE email = ?", (str(body.get("email") or "").strip().lower(),))
                if not u:
                    raise err(404, "No account with that email.")
                g = guarantee.grant(c, cfg, u["id"], str(body.get("kind") or "interview"), p.uid)
                send(c, u["email"], mail.guarantee(cfg.public_url, g["kind"], "enrolled"))
                return {"ok": True, "status": g["status"], "endsAt": g["ends_at"]}
        except guarantee.GuaranteeError as e:
            raise gerr(e) from None

    @app.post("/api/guarantee/{kind}/claim")
    def guarantee_claim(kind: str, request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        if kind not in guarantee.KINDS:
            raise err(404, "Not found.")
        try:
            with db.tx() as c:
                limited(c, f"guarantee-claim:{p.uid}", 5, 86400)
                guarantee.claim(c, cfg, p.uid, kind, body.get("attest") is True, str(body.get("note") or ""), client_ip(request))
                for to in staff_emails(c):
                    send(c, to, mail.guarantee(cfg.public_url, kind, "staff-claim"))
                return guarantee.view(c, cfg, p.user)
        except guarantee.GuaranteeError as e:
            raise gerr(e) from None

    @app.get("/api/staff/guarantees")
    def staff_guarantees(p: Principal = Depends(staff_only)):
        with db.tx() as c:
            repo.audit(c, p.uid, "guarantee-claims-viewed", "")
            return {"claims": guarantee.staff_list(c, cfg), "days": cfg.guarantee_days}

    @app.post("/api/staff/guarantees/{gid}/{decision}")
    def staff_guarantee_decide(gid: str, decision: str, body: dict = Body(default={}), p: Principal = Depends(staff_only)):
        amount = body.get("amount")
        try:
            amount = None if amount in (None, "") else int(amount)
        except (TypeError, ValueError):
            raise err(400, "The amount must be a whole number in paise or cents.", "guarantee") from None
        try:
            with db.tx() as c:
                g = guarantee.decide(c, cfg, p.uid, gid, decision, str(body.get("note") or ""), amount)
                u = c.one("SELECT email FROM users WHERE id = ?", (g["user_id"],))
                what = {"approve": "approved", "reject": "rejected", "accept": "accepted", "decline": "declined"}.get(decision)
                if u and what:
                    send(c, u["email"], mail.guarantee(cfg.public_url, g["kind"], what))
                return {"claims": guarantee.staff_list(c, cfg), "days": cfg.guarantee_days}
        except guarantee.GuaranteeError as e:
            raise gerr(e) from None

    @app.get("/staff", include_in_schema=False)
    def staff_page(request: Request, p: Principal = Depends(staff_only)):
        return html("staff.html", request.state.nonce)

    @app.get("/api/staff/cases")
    def staff_list(status: str = "", p: Principal = Depends(staff_only)):
        with db.tx() as c:
            return {"cases": concierge.staff_cases(c, p.user, status if status in concierge.CASE_STATUSES else ""), "me": {"id": p.uid, "name": p.user["name"]}}

    @app.get("/api/staff/cases/{cid}")
    def staff_open(cid: str, request: Request, p: Principal = Depends(staff_only)):
        try:
            with db.tx() as c:
                out = concierge.staff_case(c, cfg, cid, p.user)
                repo.audit(c, p.uid, "concierge-case-viewed", client_ip(request), {"case": cid})
                return out
        except concierge.ConciergeError as e:
            raise cerr(e)

    def _staff_case(c, cid: str, p: Principal) -> dict:
        case = c.one("SELECT * FROM concierge_cases WHERE id = ?", (cid,))
        if not case or not concierge.can_open(case, p.user):
            raise concierge.ConciergeError("Not found.")
        return case

    @app.post("/api/staff/cases/{cid}/{action}")
    def staff_act(cid: str, action: str, request: Request, body: dict = Body(default={}), p: Principal = Depends(staff_only)):
        try:
            with db.tx() as c:
                case = _staff_case(c, cid, p)
                owner = c.one("SELECT id, email FROM users WHERE id = ?", (case["user_id"],))
                if action == "decline":
                    # A Job Guarantee (Concierge) application the team doesn't accept: closed with a reason the member reads.
                    why = " ".join(str(body.get("reason") or "").split())[:600]
                    if case["status"] != "requested":
                        raise concierge.ConciergeError("Only an application waiting for review can be declined.")
                    if len(why) < 10:
                        raise concierge.ConciergeError("Say why, in a sentence the member will read.")
                    concierge.set_status(c, cid, "closed", "Not accepted: " + why)
                    send(c, owner["email"], mail.concierge(cfg.public_url, "declined"))
                elif action == "take":
                    if case["partner_id"] and case["partner_id"] != p.uid and not p.user["is_admin"]:
                        raise concierge.ConciergeError("Another partner has this case.")
                    c.execute("UPDATE concierge_cases SET partner_id = ?, status = CASE WHEN status = 'requested' THEN 'active' ELSE status END, updated_at = ? WHERE id = ?",
                              (str(body.get("partnerId") or p.uid) if p.user["is_admin"] else p.uid, now_iso(), cid))
                    if case["status"] == "requested":
                        send(c, owner["email"], mail.concierge(cfg.public_url, "accepted"))
                elif action == "status":
                    concierge.set_status(c, cid, str(body.get("status") or ""), str(body.get("reason") or ""))
                elif action == "note":
                    shared = bool(body.get("shared", True))
                    concierge.add_note(c, cid, p.uid, str(body.get("body") or ""), shared)
                    if shared:
                        send(c, owner["email"], mail.concierge(cfg.public_url, "message"))
                elif action == "propose":
                    concierge.propose(c, cid, p.uid, str(body.get("company") or ""), str(body.get("title") or ""), str(body.get("url") or ""), str(body.get("why") or ""))
                    send(c, owner["email"], mail.concierge(cfg.public_url, "proposed"))
                elif action == "move":
                    concierge.move(c, cid, str(body.get("submissionId") or ""), str(body.get("status") or ""))
                elif action == "verify":
                    pl = c.one("SELECT * FROM concierge_placements WHERE id = ? AND case_id = ?", (str(body.get("placementId") or ""), cid))
                    if not pl:
                        raise concierge.ConciergeError("Not found.")
                    concierge.verify_placement(c, cfg, pl["id"], p.uid, body.get("fixedCtc"), body.get("joiningDate"))
                    send(c, owner["email"], mail.concierge(cfg.public_url, "fee-due"))
                elif action == "end-early":
                    pl = c.one("SELECT * FROM concierge_placements WHERE id = ? AND case_id = ?", (str(body.get("placementId") or ""), cid))
                    if not pl:
                        raise concierge.ConciergeError("Not found.")
                    concierge.end_early(c, pl["id"], bool(body.get("byEmployer")))
                else:
                    raise concierge.ConciergeError("Not found.")
                repo.audit(c, p.uid, f"concierge-staff-{action}", client_ip(request), {"case": cid})
                return concierge.staff_case(c, cfg, cid, p.user)
        except concierge.ConciergeError as e:
            raise cerr(e)

    @app.post("/api/admin/staff")
    def admin_staff(request: Request, body: dict = Body(...), p: Principal = Depends(admin_only)):
        """Make someone a talent partner (or remove them)."""
        with db.tx() as c:
            u = c.one("SELECT id FROM users WHERE email = ?", (str(body.get("email") or "").strip().lower(),))
            if not u:
                raise err(404, "No account with that email.")
            on = bool(body.get("staff", True))
            c.execute("UPDATE users SET is_staff = ? WHERE id = ?", (1 if on else 0, u["id"]))
            if not on:
                c.execute("UPDATE concierge_cases SET partner_id = NULL, status = CASE WHEN status = 'active' THEN 'requested' ELSE status END WHERE partner_id = ?", (u["id"],))
            repo.audit(c, u["id"], "staff-granted" if on else "staff-removed", client_ip(request), {"by": p.uid})
        return {"ok": True, "staff": on}

    # ------------------------------------------------------------ AI actions
    @app.put("/api/me/ai-key")
    def save_ai_key(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        with db.tx() as c:
            limited(c, f"aikey:{p.uid}", 20, 3600)
            try:
                saved = plans.save_key(c, cfg, p.uid, str(body.get("provider", "")), str(body.get("key", "")),
                                       str(body.get("model", "")), str(body.get("baseUrl", "")))
            except ValueError as e:
                raise err(400, str(e), "invalid_key")
            except plans.BillingError as e:
                raise err(503, str(e), "unavailable")
            repo.audit(c, p.uid, "ai-key-saved", client_ip(request), {"provider": saved["provider"]})
        return {"ownKey": saved}

    @app.delete("/api/me/ai-key")
    def delete_ai_key(request: Request, p: Principal = Depends(session_only)):
        with db.tx() as c:
            plans.delete_key(c, p.uid)
            repo.audit(c, p.uid, "ai-key-removed", client_ip(request))
        return {"ok": True}

    @app.post("/api/me/ai-key/test")
    async def test_ai_key(p: Principal = Depends(session_only)):
        with db.tx() as c:
            limited(c, f"aitest:{p.uid}", 10, 3600)
            try:
                own = plans.own_config(c, cfg, p.uid)
            except Exception:  # noqa: BLE001 - a key saved under another SECRETS_KEY can't be read
                raise err(400, "Your saved key can't be read any more. Save it again.", "invalid_key")
        if not own:
            raise err(400, "Save a key first.", "no_key")
        try:
            text = await run_in_threadpool(llm.complete, "Reply with the single word OK.", "quick", "", 8, False, own, 30)
        except llm.LLMError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "model": own.model, "reply": text.strip()[:20]}

    @app.post("/api/ai")
    async def ai_action(request: Request, body: dict = Body(default={}), p: Principal = Depends(session_only)):
        prompt = str(body.get("prompt") or "")
        if not prompt.strip():
            raise err(400, "The prompt is empty.")
        if len(prompt) > llm.MAX_PROMPT:
            raise err(413, "That's too long for one AI action.", "too_large")
        tier = body.get("tier") if body.get("tier") in llm.TIERS else "default"
        feature = str(body.get("feature") or "")[:20]
        with db.tx() as c:
            limited(c, f"ai:{p.uid}", 40, 600)
            try:
                model = plans.own_config(c, cfg, p.uid)
            except Exception:  # noqa: BLE001
                raise err(400, "Your saved AI key can't be read any more. Save it again in Settings.", "invalid_key")
            kind = "own"
            if model:
                plans.take_credit(c, p.uid, "own")
            else:
                model, kind = plans.hosted_config(), "hosted"
                # The service pays for its own model: quick tasks (parsing, scoring, copilot, mocks, drafts) run on the
                # quick model, and only the writing a recruiter reads (tailored resume and its edits) on the main one.
                tier = plans.hosted_tier(tier, feature)
                if not model:
                    raise err(503, "AI isn't available on this server. Add your own key in Settings.", "ai_off")
                plan = plans.plan_of(c, p.user)
                ok, why = plans.take_feature(c, cfg, p.uid, plan, feature)
                if not ok:
                    raise err(402, why, "plan_limit")
                limit = plans.plan_info(cfg, plan)["aiCredits"]
                if not plans.take_credit(c, p.uid, "hosted", limit):
                    hint = "Upgrade to Pro or add your own key in Settings." if plan == "free" else "Add your own key in Settings to keep going."
                    raise err(402, f"You've used this month's {limit} AI actions. {hint}", "ai_quota")
        def call(m):
            if body.get("json"):
                return {"json": llm.complete_json(prompt, tier=tier, max_tokens=8000, cfg=m)}
            return {"text": llm.complete(prompt, tier=tier, max_tokens=8000, cfg=m)}
        try:
            try:
                out = await run_in_threadpool(call, model)
            except llm.LLMError:
                backup = plans.hosted_fallback() if kind == "hosted" else None
                if not backup:
                    raise
                log.warning(json.dumps({"event": "llm-fallback", "from": model.provider, "to": backup.provider}))
                out = await run_in_threadpool(call, backup)
        except llm.LLMError as e:
            with db.tx() as c:
                plans.refund_credit(c, p.uid, kind)
                if kind == "hosted":
                    plans.refund_feature(c, p.uid, feature)
            msg = str(e) if kind == "own" else "The AI model didn't answer. Your action wasn't counted; try again."
            raise err(502, msg, "llm_error")
        return dict(out, source=kind)

    # ------------------------------------------------------------ operators
    @app.post("/api/admin/grant")
    def admin_grant(request: Request, body: dict = Body(default={}), p: Principal = Depends(admin_only)):
        email = str(body.get("email", "")).strip().lower()
        until = str(body.get("until") or "").strip() or None
        if until and not re.match(r"^\d{4}-\d{2}-\d{2}$", until):
            raise err(400, "Use a date like 2026-12-31 for until.")
        with db.tx() as c:
            u = repo.user_by_email(c, email)
            if not u:
                raise err(404, "No account with that email.")
            plan = str(body.get("plan") or "pro").lower()
            if plan not in plans.PLAN_IDS:
                raise err(400, "Plan must be free, pro or ultra.")
            if plan == "free":
                c.execute("DELETE FROM subscriptions WHERE user_id = ? AND provider = 'manual'", (u["id"],))
            else:
                plans.grant(c, u["id"], p.uid, until + "T23:59:59Z" if until else None, plan)
            repo.audit(c, u["id"], "plan-granted", client_ip(request), {"by": p.uid, "until": until, "plan": plan})
            return {"ok": True, "plan": plans.plan_of(c, repo.user_by_id(c, u["id"]))}

    @app.get("/api/admin/audit")
    def admin_audit(kind: str = "", limit: int = 100, p: Principal = Depends(admin_only)):
        """Recent security and billing events across accounts, for operators. Details hold no secrets."""
        limit = max(1, min(int(limit), 500))
        with db.tx() as c:
            rows = c.all("SELECT a.at, a.kind, a.detail, u.email FROM audit_events a LEFT JOIN users u ON u.id = a.user_id "
                         + ("WHERE (a.kind = ? OR a.kind LIKE ?) " if kind else "") + "ORDER BY a.at DESC LIMIT ?",
                         ((kind, kind.replace("%", "").replace("_", "") + "-%", limit) if kind else (limit,)))  # "guarantee" also matches "guarantee-…"
            repo.audit(c, p.uid, "admin-audit-read", "", {"kind": kind[:40]})
        return {"events": [dict(r, detail=json.loads(r["detail"] or "{}")) for r in rows]}

    @app.get("/admin", include_in_schema=False)
    def admin_page(request: Request, p: Principal = Depends(admin_only)):
        return html("admin.html", request.state.nonce)

    @app.get("/api/admin/user")
    def admin_user(email: str = "", p: Principal = Depends(admin_only)):
        """One account, for support: plan, status and security settings. No resume, documents or messages."""
        with db.tx() as c:
            u = repo.user_by_email(c, security.normalize_email(email))
            if not u:
                raise err(404, "No account with that email.")
            seat = partners.student_of(c, u["id"])
            sessions = c.scalar("SELECT COUNT(*) AS n FROM sessions WHERE user_id = ? AND expires_at > ?", (u["id"], now_iso()))
            repo.audit(c, p.uid, "admin-user-read", "", {"user": u["id"]})
            return {"id": u["id"], "email": u["email"], "name": u["name"], "createdAt": u["created_at"], "lastLoginAt": u["last_login_at"],
                    "verified": bool(u["email_verified_at"]), "disabled": bool(u["disabled_at"]), "isAdmin": bool(u["is_admin"]),
                    "isStaff": bool(u.get("is_staff")), "mfa": mfa.enabled(u), "plan": plans.plan_of(c, u), "sessions": sessions,
                    "partner": partners.branding(seat), "signIn": "LinkedIn only" if str(u["password_hash"]).startswith("!") else "password"}

    @app.post("/api/admin/disable")
    def admin_disable(request: Request, body: dict = Body(...), p: Principal = Depends(admin_only)):
        """Suspend an account (signs it out everywhere) or switch it back on."""
        email = security.normalize_email(str(body.get("email") or ""))
        on = body.get("disabled", True) is not False
        with db.tx() as c:
            u = repo.user_by_email(c, email)
            if not u:
                raise err(404, "No account with that email.")
            if u["id"] == p.uid:
                raise err(400, "You can't suspend your own account.")
            c.execute("UPDATE users SET disabled_at = ?, updated_at = ? WHERE id = ?", (now_iso() if on else None, now_iso(), u["id"]))
            if on:
                c.execute("DELETE FROM sessions WHERE user_id = ?", (u["id"],))
                c.execute("DELETE FROM api_tokens WHERE user_id = ?", (u["id"],))
            repo.audit(c, u["id"], "account-suspended" if on else "account-restored", client_ip(request), {"by": p.uid})
        return {"ok": True, "disabled": on}

    @app.get("/api/admin/overview")
    def admin_overview(p: Principal = Depends(admin_only)):
        with db.tx() as c:
            return {
                "users": c.scalar("SELECT COUNT(*) AS n FROM users"),
                "verifiedUsers": c.scalar("SELECT COUNT(*) AS n FROM users WHERE email_verified_at IS NOT NULL"),
                "activeLast7Days": c.scalar("SELECT COUNT(*) AS n FROM users WHERE last_login_at > ?", (now_iso(timedelta(days=-7)),)),
                "activeJobs": c.scalar("SELECT COUNT(*) AS n FROM jobs WHERE active = 1"),
                "feed": feed_state(c),
                "tasks": c.all("SELECT kind, status, COUNT(*) AS n FROM tasks GROUP BY kind, status ORDER BY kind, status"),
                "recentFailures": c.all("SELECT kind, last_error, finished_at FROM tasks WHERE status = 'failed' ORDER BY finished_at DESC LIMIT 10"),
                "plans": c.all("SELECT plan, status, COUNT(*) AS n FROM subscriptions GROUP BY plan, status ORDER BY plan, status"),
                "aiThisMonth": c.one("SELECT COALESCE(SUM(hosted), 0) AS hosted, COALESCE(SUM(own), 0) AS own FROM ai_usage WHERE period = ?",
                                     (plans.period(),)),
                "billingEnabled": cfg.billing_enabled,
                "hostedAi": plans.hosted_config() is not None,
            }

    @app.get("/api/admin/funnel")
    def admin_funnel(days: int = 14, p: Principal = Depends(admin_only)):
        """Sign-ups in the last `days` days by where they came from, and how far each group got: confirmed the email,
        built a profile, got matches, applied, pays. Counts only; no person is listed."""
        days = max(1, min(int(days), 365))
        since = now_iso(timedelta(days=-days))
        def step(cond: str, name: str) -> str:
            return "SUM(CASE WHEN " + cond + " THEN 1 ELSE 0 END) AS " + name

        def has(where: str) -> str:
            return "EXISTS (SELECT 1 FROM docs d WHERE d.user_id = u.id AND " + where + ")"
        paying = ("(EXISTS (SELECT 1 FROM subscriptions s WHERE s.user_id = u.id AND s.plan IN ('pro', 'ultra') AND s.status IN ('active', 'pending')) "
                  "OR EXISTS (SELECT 1 FROM passes x WHERE x.user_id = u.id AND x.status = 'paid'))")
        cols = ", ".join([
            step("u.email_verified_at IS NOT NULL", "confirmed"),
            step(has("d.collection = 'brain' AND d.id = 'brain'"), "profile"),
            step(has("d.collection = 'jobs'"), "matched"),
            step(has("d.collection = 'jobs' AND d.data LIKE '%\"appliedAt\"%'"), "applied"),
            step(paying, "paying")])
        sql = ("SELECT CASE WHEN u.signup_source = '' THEN 'direct' ELSE u.signup_source END AS source, COUNT(*) AS signups, " + cols
               + " FROM users u WHERE u.created_at > ? GROUP BY 1 ORDER BY 2 DESC LIMIT 60")
        with db.tx() as c:
            rows = c.all(sql, (since,))
            seats = c.scalar("SELECT COUNT(*) AS n FROM partner_members WHERE status = 'active' AND role = 'student'")
        keys = ("signups", "confirmed", "profile", "matched", "applied", "paying")
        rows = [{"source": r["source"], **{k: int(r[k] or 0) for k in keys}} for r in rows]
        return {"days": days, "since": since, "total": {k: sum(r[k] for r in rows) for k in keys}, "bySource": rows, "businessSeats": int(seats or 0)}

    return app
