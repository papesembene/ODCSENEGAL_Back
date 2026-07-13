"""Small helpers for consistent SendGrid error reporting."""

import json


def sendgrid_error_detail(error):
    body = getattr(error, "body", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if not body:
        return str(error)
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return str(body)
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        messages = [
            item.get("message", "")
            for item in errors
            if isinstance(item, dict) and item.get("message")
        ]
        if messages:
            return " | ".join(messages)
    return str(payload)


def sendgrid_response_detail(response):
    body = getattr(response, "body", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    return body or f"Statut SendGrid {getattr(response, 'status_code', '-')}"
