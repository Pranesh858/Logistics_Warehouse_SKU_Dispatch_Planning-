"""Getting an alert to a person who is not looking at the screen.

In-app is always on and needs nothing configured: the alert row *is* the in-app delivery. Beyond that, an
installation pushes alerts wherever it already watches things, so nothing here is tied to one vendor:

  webhook  ALERT_WEBHOOK_URL - a POST of the alert as JSON. This is what Slack, Teams, PagerDuty, Opsgenie
           and every monitoring tool accept, so one setting covers all of them.
  email    ALERT_EMAIL_TO plus the SMTP settings - plain SMTP, so it works with a company mail server or a
           provider, with no library to install.

Both are off until configured, and neither can break the thing that raised the alert: a delivery failure is
recorded on the alert and nothing else. An alert that is never delivered is still in the list.
"""
import json
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from app.core.config import settings

TIMEOUT = 10.0


def channels() -> list[str]:
    """Which outside channels are configured. Empty means in-app only, which is a valid install."""
    out = []
    if settings.alert_webhook_url.strip():
        out.append("webhook")
    if settings.alert_email_to.strip() and settings.smtp_host.strip():
        out.append("email")
    return out


def payload(alert) -> dict:
    return {
        "id": alert.id,
        "kind": alert.kind,
        "severity": alert.severity,
        "title": alert.title,
        "detail": alert.detail,
        "warehouse_id": alert.warehouse_id,
        "product_id": alert.product_id,
        "occurrences": alert.occurrences,
        "first_seen": alert.first_seen.isoformat() if alert.first_seen else None,
        "last_seen": alert.last_seen.isoformat() if alert.last_seen else None,
        "source": "warehouse-dispatch-planning",
    }


def _send_webhook(alert) -> None:
    headers = {"Content-Type": "application/json"}
    if settings.alert_webhook_key.strip():
        headers["X-Alert-Key"] = settings.alert_webhook_key.strip()
    body = payload(alert)
    # Chat tools show the "text" field and ignore the rest; monitoring tools read the fields. One body suits both.
    body["text"] = f"[{alert.severity}] {alert.title}" + (f"\n{alert.detail}" if alert.detail else "")
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(settings.alert_webhook_url.strip(), json=body, headers=headers)
        r.raise_for_status()


def _send_email(alert) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"[{alert.severity}] {alert.title}"
    msg["From"] = settings.smtp_from.strip() or settings.alert_email_to.strip()
    msg["To"] = settings.alert_email_to.strip()
    lines = [alert.detail or alert.title, ""]
    if alert.warehouse_id:
        lines.append(f"Warehouse: {alert.warehouse_id}")
    if alert.product_id:
        lines.append(f"SKU: {alert.product_id}")
    lines.append(f"Seen {alert.occurrences} time(s), most recently {alert.last_seen}.")
    msg.set_content("\n".join(lines))

    host, port = settings.smtp_host.strip(), settings.smtp_port
    if settings.smtp_use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=TIMEOUT)
    with server:
        if settings.smtp_use_tls and not settings.smtp_use_ssl:
            server.starttls(context=ssl.create_default_context())
        if settings.smtp_user.strip():
            server.login(settings.smtp_user.strip(), settings.smtp_password)
        server.send_message(msg)


# Looked up when an alert is sent, not when this module loads. Holding the function objects in the dict
# froze them: replacing a sender - to test delivery, or to swap in an installation's own transport - had no
# effect, because the dict still pointed at the original.
SENDERS = {"webhook": lambda alert: _send_webhook(alert), "email": lambda alert: _send_email(alert)}


def send(alert) -> str:
    """Push the alert to every configured channel. Returns what happened, to store on the alert.

    Blocking: callers run this off the event loop. Nothing here raises; a channel that fails is named in the
    returned string so an admin can see the delivery broke without the alert itself being lost.
    """
    results = {}
    for name in channels():
        try:
            SENDERS[name](alert)
            results[name] = "sent"
        except Exception as exc:  # noqa: BLE001
            results[name] = f"failed: {exc}"[:200]
    return json.dumps(results) if results else ""


def probe() -> dict:
    """Does the delivery configuration actually work? Sends one test alert to every configured channel."""
    class _Test:
        id, kind, severity = 0, "test", "INFO"
        title = "Test alert from the dispatch planner"
        detail = "If you can read this, alert delivery is configured correctly."
        warehouse_id, product_id, occurrences = None, None, 1
        first_seen = last_seen = None

    found = channels()
    if not found:
        return {"channels": [], "ok": False,
                "message": "No outside channel is configured, so alerts appear in the app only. "
                           "Set ALERT_WEBHOOK_URL, or ALERT_EMAIL_TO with the SMTP settings."}
    raw = send(_Test())
    results = json.loads(raw) if raw else {}
    ok = all(v == "sent" for v in results.values())
    return {"channels": found, "ok": ok, "results": results,
            "message": "Test alert sent." if ok else "Some channels failed; see results."}
