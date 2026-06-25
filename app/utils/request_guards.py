import re
import time
from collections import defaultdict
from threading import Lock


RATE_LIMIT_STORE = defaultdict(list)
MAX_RATE_LIMIT_KEYS = 10000
RATE_LIMIT_LOCK = Lock()


def normalize_email(value):
    return (value or "").strip().lower()


def normalize_phone(value):
    return re.sub(r"[^\d+]", "", (value or "").strip())


def is_request_rate_limited(scope, identifier, limit=10, window=60):
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
