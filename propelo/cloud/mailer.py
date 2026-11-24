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

log = logging.getLogger("propelo.mail")
OUTBOX: list[dict] = []  # development and tests read sent mail here


class Mailer:
    def __init__(self, smtp_url: str, mail_from: str, reply_to: str = ""):
        self.url, self.mail_from = smtp_url or "console://", mail_from
        # Replies go to the support inbox: the sending address is often one nobody reads.
        self.reply_to = reply_to.strip() if "@" in reply_to and reply_to.strip() not in mail_from else ""

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.mail_from, to, subject
        if self.reply_to:
            msg["Reply-To"] = self.reply_to
        msg["Message-ID"] = make_msgid(domain=(self.mail_from.rsplit("@", 1)[-1].strip("> ") or "localhost"))
        msg.set_content(text)
        u = urlparse(self.url)
        if u.scheme == "console":
            OUTBOX.append({"to": to, "subject": subject, "text": text, "replyTo": msg["Reply-To"] or ""})
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
        "accepted": ("Your Job Guarantee application is accepted", "Good news: a talent partner has taken your case and will introduce themselves in the app.\n\n{u}/app#concierge\n\nYou pay nothing until you join a company you approved through us."),
        "declined": ("About your Job Guarantee application", "We couldn't accept your application this time. The reason is in the app, and you can reply to this email if you'd like to talk it through.\n\n{u}/app#concierge\n"),
        "fee-due": ("Your first Concierge instalment", "Congratulations on the new job. Your first instalment is now payable from Propelo; the amount and due dates are in your case.\n\n{u}/app#concierge\n"),
    }
    subject, body = texts[what]
    return subject, body.replace("{u}", public_url)


def guarantee(public_url: str, kind: str, what: str) -> tuple[str, str]:
    """Interview Guarantee notices. The details stay in the app."""
    texts = {
        "applied": ("We got your Interview Guarantee application", "Thanks for applying. A person on the team reviews it within 2 working days. You pay only if we accept it.\n\n{u}/app#guarantee\n"),
        "staff-applied": ("New Interview Guarantee application", "A member applied for the Interview Guarantee. Review it in the workspace: {u}/staff#guarantees\n"),
        "accepted": ("Your Interview Guarantee is accepted", "We accepted your application. Pay from the app within 7 days and your 45 days start right away.\n\n{u}/app#guarantee\n"),
        "declined": ("About your Interview Guarantee application", "We couldn't accept your application this time. The reason is in the app; you can reply to this email or apply again later.\n\n{u}/app#guarantee\n"),
        "enrolled": ("Your Interview Guarantee has started", "Your payment went through and your 45 days have started. Your progress and the rules are in the app:\n\n{u}/app#guarantee\n"),
        "met": ("Congratulations", "You reached the interviews we promised, so your Interview Guarantee is complete. Good luck!\n\nPrepare with Propelo: {u}/app#guarantee\n"),
        "claimable": ("Your Interview Guarantee refund can be claimed", "Your window ended short of what we promised, and you did your part. Claim your refund in the app:\n\n{u}/app#guarantee\n"),
        "void": ("Your Interview Guarantee has stopped", "Your Interview Guarantee stopped because your plan ended before the window did. Details: {u}/app#guarantee\n"),
        "approved": ("Your refund is approved", "We approved your Interview Guarantee claim. The refund goes to your original payment method, usually within 5 to 7 working days.\n\n{u}/app#guarantee\n"),
        "rejected": ("About your guarantee claim", "We couldn't approve your Interview Guarantee claim. The reason is in the app, and you can reply to this email if you think we got it wrong.\n\n{u}/app#guarantee\n"),
        "staff-claim": ("New guarantee claim", "Someone claimed an Interview Guarantee refund. Check it in the workspace: {u}/staff#guarantees\n"),
    }
    subject, body = texts[what]
    return subject, body.replace("{u}", public_url)


def pass_started(public_url: str, days: int, ends_at: str, plan: str = "pro") -> tuple[str, str]:
    """A pass was paid for: Pro or Ultra for a fixed number of days, with nothing that renews."""
    until, name = (ends_at or "")[:10], "Ultra" if plan == "ultra" else "Pro"
    return (f"Your {name} pass has started", f"Thanks. Your payment went through and {name} is on for {days} days, until {until}. "
            f"Nothing renews and there is nothing to cancel.\n\n{public_url}/app\n")


def business(public_url: str, what: str, name: str = "") -> tuple[str, str]:
    """Business account notices (consultancies and agencies)."""
    n = name or "your business account"
    texts = {
        "requested": ("We got your pilot request", f"Thanks for asking for a free pilot for {n}. A person on the team replies within 2 working days.\n\nYour business page: {{u}}/partner\n"),
        "staff-requested": ("New business pilot request", f"{n} asked for a free pilot. Review it at {{u}}/partner (staff section).\n"),
        "pilot": ("Your free pilot has started", f"Your 30-day pilot for {n} is on. Share your invite link or set up your feed here:\n\n{{u}}/partner\n"),
        "paid": ("Payment received", f"Thanks. Your payment for {n} went through and your account runs for the next 30 days. Nothing renews by itself; we'll remind you a week before it ends.\n\n{{u}}/partner\n"),
        "soon": ("Your business account ends in a week", f"{n} ends in 7 days or less. Pay for the next 30 days from your business page to keep it running; nothing renews by itself.\n\n{{u}}/partner\n"),
        "ended": ("Your business account has ended", f"{n} has ended, so students' seats and the roles feed are paused. Pay from your business page to switch it back on; nothing was deleted.\n\n{{u}}/partner\n"),
    }
    subject, body = texts[what]
    return subject, body.replace("{u}", public_url)

