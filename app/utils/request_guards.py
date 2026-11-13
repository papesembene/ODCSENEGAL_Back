import re
import time
import unicodedata
import hashlib
import hmac
import os
from collections import defaultdict
from threading import Lock
from app.utils.shared_rate_limit import shared_rate_limited
from flask import request
from werkzeug.exceptions import BadRequest, TooManyRequests


RATE_LIMIT_STORE = defaultdict(list)
MAX_RATE_LIMIT_KEYS = 10000
RATE_LIMIT_LOCK = Lock()


def normalize_email(value):
    return (value or "").strip().lower()


def normalize_phone(value):
    return re.sub(r"[^\d+]", "", (value or "").strip())


def normalize_candidate_name(value):
    normalized = unicodedata.normalize("NFKD", (value or "").casefold())
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def candidature_identity_fingerprint(phone, birth_date, first_name, last_name):
    secret = os.getenv("CANDIDATURE_IDENTITY_SECRET") or os.getenv("SECRET_KEY", "dev_key")
    identity = "\x1f".join((
        normalize_phone(phone),
        birth_date.isoformat(),
        normalize_candidate_name(first_name),
        normalize_candidate_name(last_name),
    ))
    return hmac.new(secret.encode("utf-8"), identity.encode("utf-8"), hashlib.sha256).hexdigest()


def login_credentials(data):
    if not isinstance(data, dict):
        raise BadRequest("Email et mot de passe requis")
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str) or not email.strip() or not password or len(email) > 254 or len(password) > 1024:
        raise BadRequest("Identifiants invalides")
    email = normalize_email(email)
    if is_request_rate_limited("login_ip", request.remote_addr, limit=300, window=300) or is_request_rate_limited("login_account", email, limit=10, window=300):
        raise TooManyRequests("Trop de tentatives de connexion, veuillez réessayer plus tard")
    return email, password


def is_request_rate_limited(scope, identifier, limit=10, window=60):
    shared = shared_rate_limited(f"request:{scope}:{identifier or 'anonymous'}", limit, window)
    if shared is not None:
        return shared
    with RATE_LIMIT_LOCK:
        now = time.time()
        key = f"{scope}:{identifier or 'anonymous'}"

        if len(RATE_LIMIT_STORE) > MAX_RATE_LIMIT_KEYS:
            stale_keys = [
                existing_key
                for existing_key, attempts in RATE_LIMIT_STORE.items()
                if not attempts or now - attempts[-1] >= window
            ]
            for stale_key in stale_keys:
                RATE_LIMIT_STORE.pop(stale_key, None)

        attempts = RATE_LIMIT_STORE[key]
        RATE_LIMIT_STORE[key] = [
            attempt
            for attempt in attempts
            if now - attempt < window
        ]
        if len(RATE_LIMIT_STORE[key]) >= limit:
            return True
        RATE_LIMIT_STORE[key].append(now)
        return False
