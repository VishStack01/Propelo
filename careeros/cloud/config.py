"""Configuration from environment variables. Every value has a development default;
production refuses to start without the settings that matter (see `check`)."""

from __future__ import annotations

import re

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_FEED = "https://github.com/VishStack01/Propelo/releases/download/feed-latest/"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _list(name: str) -> list[str]:
    return [x.strip().lower() for x in os.environ.get(name, "").split(",") if x.strip()]


def _site_url(v: str) -> str:
    """The job board's address with a trailing slash, or '' when it isn't a plain https (or local http) URL."""
    v = (v or "").strip()
    if not re.match(r"^(https://[a-z0-9.-]+(:\d+)?|http://(127\.0\.0\.1|localhost)(:\d+)?)(/[\w./-]*)?$", v, re.I):
        return ""
    return v if v.endswith("/") else v + "/"


@dataclass
class Config:
    app_env: str = "development"  # development | staging | production
    database_url: str = "sqlite:///data/cloud.db"
    public_url: str = "http://127.0.0.1:8000"
    jobs_site_url: str = "https://propelo.org/"  # the public job board; the app shows its company logos
    upload_dir: Path = Path("data/uploads")
    storage: str = "disk"       # STORAGE=db keeps uploaded files in the database, for a server with no disk of its own
    all_in_one: bool = False    # ALL_IN_ONE=on: `careeros cloud serve` also migrates and runs the worker (one small server)
    max_upload_mb: int = 5
    user_storage_mb: int = 25
    session_ttl_days: int = 14
    password_iterations: int = 600_000
    smtp_url: str = ""
    mail_from: str = "Propelo <no-reply@localhost>"
    bootstrap_admin_email: str = ""
    signup_mode: str = "open"  # open | allowlist | closed
    signup_allowlist: list[str] = field(default_factory=list)  # emails or @domains
    feed_url: str = DEFAULT_FEED
    ingest_every_minutes: int = 15
    worker_poll_seconds: int = 5
    worker_lease_minutes: int = 10
    db_pool_min: int = 1
    db_pool_max: int = 10
    trust_proxy: bool = False
    max_docs_per_user: int = 5000
    max_doc_kb: int = 512
    linkedin_client_id: str = ""  # "Sign in with LinkedIn using OpenID Connect": name, email, photo only
    linkedin_client_secret: str = ""
    # Google OAuth for sending recruiter emails from the person's own Gmail (scope gmail.send only).
    # Propelo Concierge (human-run search, fee only after joining). Off unless CONCIERGE=on.
    concierge_enabled: bool = False
    concierge_countries: tuple = ("IN",)
    concierge_rate_low: float = 8.0
    concierge_rate_high: float = 6.0
    concierge_band: int = 2_000_000
    concierge_tax_rate: float = 0.0
    concierge_instalments: int = 3
    concierge_attribution_days: int = 180
    # Money-back guarantees (see guarantee.py): GUARANTEE_MIN_INTERVIEWS interviews or a second round within GUARANTEE_DAYS on Pro or Ultra, and a job
    # within JOB_GUARANTEE_DAYS with Concierge, or the plan fees paid in that time are refunded.
    guarantee_enabled: bool = False
    pass_enabled: bool = False          # PASS=on: sell Pro for a fixed number of days, paid once (passes.py)
    pass_days: int = 90
    pass_inr: int = 1199
    pass_usd_cents: int = 5400
    dodo_product_pass: str = ""        # a one-time Dodo product priced at the pass's dollar price
    guarantee_days: int = 45
    guarantee_min_apps: int = 25
    guarantee_min_weeks: int = 3
    guarantee_min_matches: int = 40
    guarantee_min_interviews: int = 3
    guarantee_claim_days: int = 30
    job_guarantee_days: int = 180
    # Pro and Ultra members apply for the Interview Guarantee; once the team accepts them they pay its price once,
    # and get it back if that doesn't happen in GUARANTEE_DAYS. The Job Guarantee has no upfront price: it is a
    # reviewed Concierge application, paid by the placement fee after joining (guarantee_job_inr is unused).
    guarantee_interview_inr: int = 4999
    guarantee_interview_usd_cents: int = 5900
    guarantee_job_inr: int = 2999
    dodo_product_guarantee: str = ""   # a one-time Dodo product priced at the Interview Guarantee's dollar price
    security_email: str = ""  # shown in /.well-known/security.txt; falls back to SUPPORT_EMAIL
    google_client_id: str = ""
    google_client_secret: str = ""
    # Plans and billing. Prices are in rupees per month; credits are AI actions per calendar month (UTC).
    secrets_key: str = ""  # encrypts users' own AI keys at rest; any long random string
    # India pays in rupees through Razorpay; everyone else pays in US dollars through Dodo Payments
    # (merchant of record: it handles VAT and sales tax). USD prices are in cents.
    pro_price_inr: int = 499
    ultra_price_inr: int = 1199
    pro_price_usd_cents: int = 2250
    ultra_price_usd_cents: int = 4850
    free_ai_credits: int = 15
    pro_ai_credits: int = 400
    ultra_ai_credits: int = 1500
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_pro: str = ""  # plan_... created in the Razorpay dashboard at pro_price_inr per month
    razorpay_plan_ultra: str = ""  # plan_... at ultra_price_inr per month
    dodo_api_key: str = ""
    dodo_webhook_secret: str = ""  # whsec_... from Dodo's webhook settings
    dodo_product_pro: str = ""  # pdt_... a monthly subscription product at pro_price_usd_cents
    dodo_product_ultra: str = ""  # pdt_... at ultra_price_usd_cents
    dodo_live: bool = False  # False uses Dodo's test mode
    support_email: str = ""
    company_name: str = "Propelo"

    @classmethod
    def from_env(cls) -> "Config":
        e = os.environ.get
        return cls(
            app_env=e("APP_ENV", "development").lower(),
            database_url=e("DATABASE_URL", "sqlite:///data/cloud.db"),
            # Render tells a web service its own address; it is used until PUBLIC_URL names the real domain.
            public_url=(e("PUBLIC_URL", "").strip() or e("RENDER_EXTERNAL_URL", "").strip() or "http://127.0.0.1:8000").rstrip("/"),
            jobs_site_url=_site_url(e("JOBS_SITE_URL", "https://propelo.org/")),
            upload_dir=Path(e("UPLOAD_DIR", "data/uploads")),
            storage=e("STORAGE", "disk").strip().lower() or "disk",
            all_in_one=e("ALL_IN_ONE", "off").strip().lower() in ("on", "1", "true", "yes"),
            max_upload_mb=_int("MAX_UPLOAD_MB", 5),
            user_storage_mb=_int("USER_STORAGE_MB", 25),
            session_ttl_days=_int("SESSION_TTL_DAYS", 14),
            password_iterations=_int("PASSWORD_ITERATIONS", 600_000),
            smtp_url=e("SMTP_URL", ""),
            mail_from=e("MAIL_FROM", "Propelo <no-reply@localhost>"),
            bootstrap_admin_email=e("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower(),
            signup_mode=e("SIGNUP_MODE", "open").lower(),
            signup_allowlist=_list("SIGNUP_ALLOWLIST"),
            feed_url=e("FEED_URL", DEFAULT_FEED),
            ingest_every_minutes=_int("INGEST_EVERY_MINUTES", 15),
            worker_poll_seconds=_int("WORKER_POLL_SECONDS", 5),
            worker_lease_minutes=_int("WORKER_LEASE_MINUTES", 10),
            db_pool_min=_int("DB_POOL_MIN", 1),
            db_pool_max=_int("DB_POOL_MAX", 10),
            trust_proxy=e("TRUST_PROXY", "0") in ("1", "true", "yes"),
            max_docs_per_user=_int("MAX_DOCS_PER_USER", 5000),
            max_doc_kb=_int("MAX_DOC_KB", 512),
            linkedin_client_id=e("LINKEDIN_CLIENT_ID", "").strip(),
            linkedin_client_secret=e("LINKEDIN_CLIENT_SECRET", "").strip(),
            concierge_enabled=e("CONCIERGE", "off").strip().lower() in ("on", "1", "true", "yes"),
            concierge_countries=tuple(x.strip().upper() for x in e("CONCIERGE_COUNTRIES", "IN").split(",") if x.strip()),
            concierge_rate_low=float(e("CONCIERGE_RATE_LOW", "8") or 8),
            concierge_rate_high=float(e("CONCIERGE_RATE_HIGH", "6") or 6),
            concierge_band=_int("CONCIERGE_BAND", 2_000_000),
            concierge_tax_rate=float(e("CONCIERGE_TAX_RATE", "0") or 0),
            concierge_instalments=_int("CONCIERGE_INSTALMENTS", 3),
            concierge_attribution_days=_int("CONCIERGE_ATTRIBUTION_DAYS", 180),
            guarantee_enabled=e("GUARANTEE", "off").strip().lower() in ("on", "1", "true", "yes"),
            pass_enabled=e("PASS", "off").strip().lower() in ("on", "1", "true", "yes"),
            pass_days=_int("PASS_DAYS", 90),
            pass_inr=_int("PASS_PRICE_INR", 1199),
            pass_usd_cents=_int("PASS_PRICE_USD_CENTS", 5400),
            dodo_product_pass=e("DODO_PRODUCT_PASS", "").strip(),
            guarantee_days=_int("GUARANTEE_DAYS", 45),
            guarantee_min_apps=_int("GUARANTEE_MIN_APPLICATIONS", 25),
            guarantee_min_weeks=_int("GUARANTEE_MIN_WEEKS", 3),
            guarantee_min_matches=_int("GUARANTEE_MIN_MATCHES", 40),
            guarantee_min_interviews=_int("GUARANTEE_MIN_INTERVIEWS", 3),
            guarantee_claim_days=_int("GUARANTEE_CLAIM_DAYS", 30),
            job_guarantee_days=_int("JOB_GUARANTEE_DAYS", 180),
            guarantee_interview_inr=_int("GUARANTEE_INTERVIEW_PRICE_INR", 4999),
            guarantee_interview_usd_cents=_int("GUARANTEE_INTERVIEW_PRICE_USD_CENTS", 5900),
            guarantee_job_inr=_int("JOB_GUARANTEE_PRICE_INR", 2999),
            dodo_product_guarantee=e("DODO_PRODUCT_GUARANTEE", "").strip(),
            security_email=e("SECURITY_EMAIL", "").strip(),
            google_client_id=e("GOOGLE_CLIENT_ID", "").strip(),
            google_client_secret=e("GOOGLE_CLIENT_SECRET", "").strip(),
            secrets_key=e("SECRETS_KEY", "").strip(),
            pro_price_inr=_int("PRO_PRICE_INR", 499),
            ultra_price_inr=_int("ULTRA_PRICE_INR", 1199),
            pro_price_usd_cents=_int("PRO_PRICE_USD_CENTS", 2250),
            ultra_price_usd_cents=_int("ULTRA_PRICE_USD_CENTS", 4850),
            free_ai_credits=_int("FREE_AI_CREDITS", 15),
            pro_ai_credits=_int("PRO_AI_CREDITS", 400),
            ultra_ai_credits=_int("ULTRA_AI_CREDITS", 1500),
            razorpay_key_id=e("RAZORPAY_KEY_ID", "").strip(),
            razorpay_key_secret=e("RAZORPAY_KEY_SECRET", "").strip(),
            razorpay_webhook_secret=e("RAZORPAY_WEBHOOK_SECRET", "").strip(),
            razorpay_plan_pro=e("RAZORPAY_PLAN_PRO", "").strip(),
            razorpay_plan_ultra=e("RAZORPAY_PLAN_ULTRA", "").strip(),
            dodo_api_key=e("DODO_API_KEY", "").strip(),
            dodo_webhook_secret=e("DODO_WEBHOOK_SECRET", "").strip(),
            dodo_product_pro=e("DODO_PRODUCT_PRO", "").strip(),
            dodo_product_ultra=e("DODO_PRODUCT_ULTRA", "").strip(),
            dodo_live=e("DODO_MODE", "test").strip().lower() == "live",
            support_email=e("SUPPORT_EMAIL", "").strip(),
            company_name=e("COMPANY_NAME", "Propelo").strip() or "Propelo",
        )

    @property
    def razorpay_enabled(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret and self.razorpay_webhook_secret and self.razorpay_plan_pro)

    @property
    def dodo_enabled(self) -> bool:
        return bool(self.dodo_api_key and self.dodo_webhook_secret and self.dodo_product_pro)

    @property
    def billing_enabled(self) -> bool:
        return self.razorpay_enabled or self.dodo_enabled

    @property
    def linkedin_enabled(self) -> bool:
        return bool(self.linkedin_client_id and self.linkedin_client_secret)

    @property
    def gmail_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.secrets_key)

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def is_production(self) -> bool:
        return self.app_env in ("production", "staging")

    def check(self) -> list[str]:
        """Problems that make this configuration unsafe to serve real users."""
        if not self.is_production:
            return []
        problems = []
        if not self.database_url.startswith(("postgres://", "postgresql://")):
            problems.append("DATABASE_URL must point at PostgreSQL in staging and production.")
        if not self.public_url.startswith("https://"):
            problems.append("PUBLIC_URL must be an https:// address in staging and production.")
        if not self.smtp_url:
            problems.append("SMTP_URL is required: sign-up and password reset send email.")
        elif not self.smtp_url.startswith(("smtp://", "smtps://", "console://")):
            problems.append("SMTP_URL must start with smtp://, smtps:// or console:// (for example smtps://user:password@smtp.example.com:465).")
        elif self.smtp_url.startswith("console://") and self.app_env == "production":
            problems.append("SMTP_URL is console:// in production: emails would only be printed to the log, so nobody could confirm their account.")
        if self.storage not in ("disk", "db"):
            problems.append("STORAGE must be disk or db.")
        if self.password_iterations < 310_000:
            problems.append("PASSWORD_ITERATIONS must be at least 310000.")
        if self.signup_mode not in ("open", "allowlist", "closed"):
            problems.append("SIGNUP_MODE must be open, allowlist or closed.")
        if len(self.secrets_key) < 32:
            problems.append("SECRETS_KEY must be a random string of at least 32 characters (it encrypts users' AI keys).")
        if any((self.razorpay_key_id, self.razorpay_key_secret, self.razorpay_webhook_secret, self.razorpay_plan_pro, self.razorpay_plan_ultra)) and not self.razorpay_enabled:
            problems.append("Billing is half set up: set all of RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET and RAZORPAY_PLAN_PRO, or none.")
        if any((self.dodo_api_key, self.dodo_webhook_secret, self.dodo_product_pro)) and not self.dodo_enabled:
            problems.append("Dodo Payments is half set up: set all of DODO_API_KEY, DODO_WEBHOOK_SECRET and DODO_PRODUCT_PRO, or none.")
        if any((self.dodo_api_key, self.dodo_webhook_secret, self.dodo_product_pro, self.dodo_product_ultra)) and not self.dodo_enabled:
            if "Dodo Payments is half set up" not in " ".join(problems):
                problems.append("Dodo Payments is half set up: set all of DODO_API_KEY, DODO_WEBHOOK_SECRET and DODO_PRODUCT_PRO, or none.")
        if self.concierge_enabled and not (0 < self.concierge_rate_high <= self.concierge_rate_low <= 8):
            problems.append("CONCIERGE_RATE_LOW and CONCIERGE_RATE_HIGH must be between 0 and 8, with the rate above the band no higher than below it.")
        if self.pass_enabled and not (7 <= self.pass_days <= 366 and self.pass_inr >= 1 and self.pass_usd_cents >= 100):
            problems.append("PASS is on but PASS_DAYS (7 to 366), PASS_PRICE_INR or PASS_PRICE_USD_CENTS is out of range.")
        if self.guarantee_enabled and not (30 <= self.guarantee_days <= 180 and 1 <= self.guarantee_min_weeks <= self.guarantee_days // 7
                                           and self.guarantee_min_apps >= 1 and 1 <= self.guarantee_min_interviews <= 10 and 90 <= self.job_guarantee_days <= 365):
            problems.append("Guarantee settings look wrong: GUARANTEE_DAYS 30 to 180, GUARANTEE_MIN_WEEKS within it, JOB_GUARANTEE_DAYS 90 to 365.")
        if self.concierge_enabled and any(cc in ("GB", "UK") for cc in self.concierge_countries):
            problems.append("Concierge can't run in the UK: charging job seekers a fee for finding work is prohibited there.")
        if (self.google_client_id or self.google_client_secret) and not (self.google_client_id and self.google_client_secret):
            problems.append("Gmail sending is half set up: set both GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or neither.")
        if self.billing_enabled and not self.support_email:
            problems.append("SUPPORT_EMAIL is required when payments are on: the refund and contact pages show it.")
        if "change_me" in self.database_url.lower():
            problems.append("DATABASE_URL still contains the example password.")
        return problems

    def signup_allowed(self, email: str) -> bool:
        if self.signup_mode == "open":
            return True
        if self.signup_mode == "closed":
            return False
        domain = "@" + email.rsplit("@", 1)[-1]
        return email in self.signup_allowlist or domain in self.signup_allowlist
