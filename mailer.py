"""Delivery over Gmail SMTP (spec Section 9).

From and To are both the user's own address — Scout has no other
recipients and will not accept one from any external source. On send
failure: one retry after a short backoff, then the brief is saved to
logs/last_brief.html so the day's work isn't lost. Never crashes the run.

Swappable by design: everything provider-specific lives in this module.
"""

from __future__ import annotations

import logging
import smtplib
import time
from email.message import EmailMessage

from config import ROOT

RETRY_BACKOFF_SECONDS = 10
FALLBACK_PATH = ROOT / "logs" / "last_brief.html"

# attachment = (filename, data: bytes, maintype, subtype)
Attachment = tuple[str, bytes, str, str]


def save_fallback(html: str, logger: logging.Logger) -> None:
    try:
        FALLBACK_PATH.parent.mkdir(exist_ok=True)
        FALLBACK_PATH.write_text(html, encoding="utf-8")
        logger.info("brief saved to %s", FALLBACK_PATH)
    except OSError as exc:
        logger.error("could not save fallback brief: %s", exc)


def send_brief(
    subject: str,
    html: str,
    text: str,
    secrets: dict,
    cfg: dict,
    logger: logging.Logger,
    attachments: list[Attachment] | None = None,
) -> bool:
    address = secrets.get("email_address", "")
    password = secrets.get("email_app_password", "")
    if not address or not password:
        logger.error(
            "EMAIL_ADDRESS / EMAIL_APP_PASSWORD not set — cannot send; saving brief to disk"
        )
        save_fallback(html, logger)
        return False

    mailer_cfg = cfg.get("mailer") or {}
    host = mailer_cfg.get("smtp_host", "smtp.gmail.com")
    port = int(mailer_cfg.get("smtp_port", 587))

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = address  # only ever the user's own address
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for filename, data, maintype, subtype in attachments or []:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    for attempt in (1, 2):
        try:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(address, password)
                smtp.send_message(msg)
            logger.info("sent %r to %s", subject, address)
            return True
        except Exception as exc:  # noqa: BLE001 — delivery must never crash the run
            logger.warning(
                "send attempt %d/2 failed: %s: %s", attempt, type(exc).__name__, exc
            )
            if attempt == 1:
                time.sleep(RETRY_BACKOFF_SECONDS)

    logger.error("email delivery failed after retry — saving brief to disk")
    save_fallback(html, logger)
    return False
