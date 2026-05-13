from __future__ import annotations

import logging
import os
import smtplib
import ssl
import traceback
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _terminal(msg: str) -> None:
    """Always visible in the console (uvicorn worker), regardless of logging config."""
    print(msg, flush=True)


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    use_starttls: bool
    use_ssl: bool


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        logger.error("Invalid integer for %s=%r - using default %s", name, raw, default)
        return default


def load_smtp_config() -> SMTPConfig | None:
    """
    Read SMTP settings from the environment (.env applied via load_dotenv).
    Returns None when email is disabled (no SMTP_HOST).
    """
    host = (os.getenv("SMTP_HOST") or "").strip()
    if not host:
        return None

    port_raw = (os.getenv("SMTP_PORT") or "587").strip()
    try:
        port = int(port_raw)
    except ValueError:
        logger.error(
            "SMTP configuration error: SMTP_PORT=%r is not a valid integer. Email disabled.",
            port_raw,
        )
        _terminal(f"[CIVITAS email] SMTP config error: invalid SMTP_PORT={port_raw!r}")
        return None

    username = (os.getenv("SMTP_USERNAME") or "").strip() or None
    password = (os.getenv("SMTP_PASSWORD") or "").strip() or None
    sender = (os.getenv("SMTP_FROM") or username or "noreply@civitas.local").strip()

    # Gmail: smtp.gmail.com:587 + STARTTLS (default), or :465 + implicit SSL (SMTP_SSL)
    use_ssl = _env_bool("SMTP_SSL", default=(port == 465))
    use_starttls = _env_bool("SMTP_STARTTLS", default=True)
    if use_ssl and use_starttls:
        logger.warning("SMTP_SSL enabled: STARTTLS will be disabled (implicit SSL).")
        use_starttls = False

    return SMTPConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        sender=sender,
        use_starttls=use_starttls,
        use_ssl=use_ssl,
    )


def log_smtp_configuration() -> None:
    """Log whether SMTP is configured (startup). Never logs passwords."""
    cfg = load_smtp_config()
    if cfg is None:
        logger.info(
            "Email: disabled - SMTP_HOST is not set. Add SMTP_* variables to .env to enable."
        )
        _terminal("[CIVITAS email] SMTP disabled: SMTP_HOST not set in environment / .env")
        return

    auth_mode = "credentials" if (cfg.username and cfg.password) else "no-auth"
    logger.info(
        "Email: configured - host=%r port=%s mode=%s STARTTLS=%s SSL=%s from=%r user=%r",
        cfg.host,
        cfg.port,
        auth_mode,
        cfg.use_starttls,
        cfg.use_ssl,
        cfg.sender,
        cfg.username or "",
    )
    _terminal(
        f"[CIVITAS email] SMTP ready: {cfg.host}:{cfg.port} "
        f"(STARTTLS={cfg.use_starttls}, implicit_SSL={cfg.use_ssl}, auth={auth_mode})"
    )
    if "gmail.com" in cfg.host.lower():
        if cfg.port == 587 and not cfg.use_starttls and not cfg.use_ssl:
            logger.warning(
                "Email: Gmail on port 587 expects STARTTLS (SMTP_STARTTLS=true, the default)."
            )
        if cfg.port == 465 and not cfg.use_ssl:
            logger.warning(
                "Email: Gmail on port 465 requires implicit SSL (set SMTP_SSL=true)."
            )


def _build_body(complaint, request) -> str:
    tracking_url = f"/track?id={complaint.id}"
    if request is not None:
        tracking_url = str(request.url_for("track_form")) + f"?id={complaint.id}"

    return (
        f"Complaint ID: #{complaint.id}\n"
        f"Current Status: {complaint.status}\n"
        f"Department: {complaint.department}\n"
        f"Tracking Link: {tracking_url}\n\n"
        "Thank you for using CIVITAS."
    )


def _smtp_send(message: EmailMessage, cfg: SMTPConfig) -> None:
    timeout = _env_int("SMTP_TIMEOUT", 30)
    debug = _env_bool("SMTP_DEBUG", False)
    context = ssl.create_default_context()

    if cfg.use_ssl:
        logger.debug("SMTP: connecting with SMTP_SSL to %s:%s", cfg.host, cfg.port)
        with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=timeout, context=context) as smtp:
            if debug:
                smtp.set_debuglevel(1)
            if cfg.username and cfg.password:
                smtp.login(cfg.username, cfg.password)
            smtp.send_message(message)
        return

    logger.debug("SMTP: connecting with SMTP to %s:%s", cfg.host, cfg.port)
    with smtplib.SMTP(cfg.host, cfg.port, timeout=timeout) as smtp:
        if debug:
            smtp.set_debuglevel(1)
        smtp.ehlo()
        if cfg.use_starttls:
            smtp.starttls(context=context)
            smtp.ehlo()
        if cfg.username and cfg.password:
            smtp.login(cfg.username, cfg.password)
        smtp.send_message(message)


def send_complaint_email(to_email: str | None, subject: str, complaint, request=None) -> bool:
    """
    Send a transactional email. Never raises: failures are logged and return False.
    """
    try:
        return _send_complaint_email_impl(to_email, subject, complaint, request)
    except Exception:
        logger.exception(
            "Email: unexpected failure (non-fatal) to=%r subject=%r",
            to_email,
            subject,
        )
        _terminal(f"[CIVITAS email] FAILED: unexpected error | to={to_email!r} | subject={subject!r}")
        return False


def _send_complaint_email_impl(to_email: str | None, subject: str, complaint, request=None) -> bool:
    if not to_email:
        logger.info("Email: skipped - no recipient (subject=%r)", subject)
        _terminal(f"[CIVITAS email] skipped: no recipient | subject={subject!r}")
        return False

    cfg = load_smtp_config()
    body = _build_body(complaint, request)

    if cfg is None:
        logger.warning(
            "Email: skipped - SMTP_HOST not set | to=%r subject=%r\n--- message body ---\n%s\n--- end ---",
            to_email,
            subject,
            body,
        )
        _terminal(
            f"[CIVITAS email] skipped: SMTP_HOST not configured | to={to_email!r} | subject={subject!r}"
        )
        return False

    message = EmailMessage()
    message["From"] = cfg.sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        _smtp_send(message, cfg)
    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "Email: SMTP AUTH FAILED (check username/app password)\n"
            "  host=%s port=%s user=%r\n"
            "  smtplib.SMTPAuthenticationError: %s\n"
            "%s",
            cfg.host,
            cfg.port,
            cfg.username,
            exc,
            traceback.format_exc(),
        )
        _terminal(
            f"[CIVITAS email] FAILED: SMTP authentication error | {cfg.host}:{cfg.port} | {exc}"
        )
        return False
    except smtplib.SMTPException as exc:
        logger.error(
            "Email: SMTP protocol error\n"
            "  host=%s port=%s to=%r subject=%r\n"
            "  %s: %s\n"
            "%s",
            cfg.host,
            cfg.port,
            to_email,
            subject,
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        _terminal(
            f"[CIVITAS email] FAILED: SMTP error | {cfg.host}:{cfg.port} | {type(exc).__name__}: {exc}"
        )
        return False
    except (OSError, ssl.SSLError) as exc:
        logger.error(
            "Email: connection/TLS error (firewall, wrong host/port, or certificate issue)\n"
            "  host=%s port=%s ssl=%s starttls=%s\n"
            "  %s: %s\n"
            "%s",
            cfg.host,
            cfg.port,
            cfg.use_ssl,
            cfg.use_starttls,
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        _terminal(
            f"[CIVITAS email] FAILED: connection/TLS | {cfg.host}:{cfg.port} | {type(exc).__name__}: {exc}"
        )
        return False

    logger.info("Email: sent OK to=%r subject=%r", to_email, subject)
    _terminal(f"[CIVITAS email] OK: sent to {to_email!r} | {subject!r}")
    return True
