"""Outgoing email: SMTP in production, an in-memory outbox in development and tests.

SMTP_URL forms:
  smtp://user:pass@host:587      STARTTLS (the usual submission port)
  smtps://user:pass@host:465     implicit TLS
  console://                     print to the log (development only)
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from urllib.parse import unquote, urlparse

log = logging.getLogger("careeros.mail")
OUTBOX: list[dict] = []  # development and tests read sent mail here


class Mailer:
    def __init__(self, smtp_url: str, mail_from: str):
        self.url, self.mail_from = smtp_url or "console://", mail_from

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.mail_from, to, subject
        msg["Message-ID"] = make_msgid(domain=(self.mail_from.rsplit("@", 1)[-1].strip("> ") or "localhost"))
        msg.set_content(text)
        u = urlparse(self.url)
        if u.scheme == "console":
            OUTBOX.append({"to": to, "subject": subject, "text": text})
            log.warning("console mail (development only, not sent) to=%s subject=%r\n%s", to, subject, text)
            return
        ctx = ssl.create_default_context()
        if u.scheme == "smtps":
            server = smtplib.SMTP_SSL(u.hostname, u.port or 465, context=ctx, timeout=20)
        elif u.scheme == "smtp":
            server = smtplib.SMTP(u.hostname, u.port or 587, timeout=20)
            server.starttls(context=ctx)
        else:
            raise ValueError("SMTP_URL must start with smtp://, smtps:// or console://")
        with server:
            if u.username:
                server.login(unquote(u.username), unquote(u.password or ""))
            server.send_message(msg)


def verify_email(name: str, link: str) -> tuple[str, str]:
    return ("Confirm your email for Propelo",
            f"Hi {name or 'there'},\n\nConfirm your email to finish creating your Propelo account:\n\n{link}\n\n"
            "The link works once and expires in 24 hours. If you didn't sign up, ignore this email.\n")


def already_registered(link: str) -> tuple[str, str]:
    return ("You already have a Propelo account",
            "Someone (probably you) tried to sign up with this email, but it already has an account.\n\n"
            f"Sign in, or reset your password here:\n\n{link}\n\nIf this wasn't you, you can ignore this email.\n")


def reset_password(link: str) -> tuple[str, str]:
    return ("Reset your Propelo password",
            f"Use this link to choose a new password:\n\n{link}\n\n"
            "It works once and expires in 1 hour. Resetting signs you out everywhere. "
            "If you didn't ask for this, ignore this email; your password stays the same.\n")


def password_changed() -> tuple[str, str]:
    return ("Your Propelo password was changed",
            "Your password was just changed and every session was signed out.\n\n"
            "If this wasn't you, reset your password now from the sign-in page.\n")


def pro_welcome(public_url: str, plan: str = "pro") -> tuple[str, str]:
    name, pace = ("Ultra", "within 15 minutes of each scan") if plan == "ultra" else ("Pro", "every hour")
    return (f"You're on Propelo {name}",
            f"Thanks for upgrading. Your account now matches new roles {pace} and has a larger monthly AI allowance.\n\n"
            f"Open your dashboard: {public_url}/\n\n"
            f"You can cancel any time under Settings, Plan. You keep {name} until the end of the month you paid for.\n")


def concierge(public_url: str, what: str) -> tuple[str, str]:
    """Short Concierge notices. The details stay in the app."""
    texts = {
        "requested": ("Your Concierge request is in", "Thanks for asking for Propelo Concierge. A talent partner will look at your profile and reply within two working days.\n\nYour case: {u}/app#concierge\n\nYou pay nothing unless you join a company we put you forward to, with your approval."),
        "proposed": ("New roles to approve", "Your talent partner proposed new roles. Nothing is sent until you approve each one.\n\nReview them: {u}/app#concierge\n"),
        "message": ("New message from your talent partner", "You have a new message in Propelo Concierge.\n\nRead it: {u}/app#concierge\n"),
        "staff-new": ("New Concierge request", "Someone asked for Concierge. Open the workspace to take the case: {u}/staff\n"),
        "staff-message": ("A candidate replied", "A Concierge candidate sent a message or answered roles: {u}/staff\n"),
        "fee-due": ("Your first Concierge instalment", "Congratulations on the new job. Your first instalment is now payable from Propelo; the amount and due dates are in your case.\n\n{u}/app#concierge\n"),
    }
    subject, body = texts[what]
    return subject, body.replace("{u}", public_url)


def guarantee(public_url: str, kind: str, what: str) -> tuple[str, str]:
    """Guarantee notices. The details stay in the app."""
    name = "Interview Guarantee" if kind == "interview" else "Job Guarantee"
    texts = {
        "enrolled": (f"You're enrolled in the {name}", f"Your {name} has started. Your progress and the rules are in the app:\n\n{{u}}/app#guarantee\n"),
        "met": ("Congratulations", f"You got " + ("an interview" if kind == "interview" else "an offer") + f", so your {name} is complete. Good luck!\n\nPrepare with Propelo: {{u}}/app#guarantee\n"),
        "claimable": (f"Your {name} refund can be claimed", f"Your {name} window ended without " + ("an interview" if kind == "interview" else "an accepted offer") +
                      f", and you did your part. Claim your refund in the app within the claim period:\n\n{{u}}/app#guarantee\n"),
        "void": (f"Your {name} has ended", f"Your {name} stopped because your plan or Concierge case ended before the window did. Details: {{u}}/app#guarantee\n"),
        "approved": ("Your refund is approved", f"We approved your {name} claim. The refund goes to your original payment method, usually within 5 to 7 working days.\n\n{{u}}/app#guarantee\n"),
        "rejected": ("About your guarantee claim", f"We couldn't approve your {name} claim. The reason is in the app, and you can reply to this email if you think we got it wrong.\n\n{{u}}/app#guarantee\n"),
        "staff-claim": ("New guarantee claim", f"Someone claimed a {name} refund. Check it in the workspace: {{u}}/staff#guarantees\n"),
    }
    subject, body = texts[what]
    return subject, body.replace("{u}", public_url)

