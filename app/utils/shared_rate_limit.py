"""Atomic cross-instance rate limits; local callers keep their existing fallback."""

from functools import lru_cache
from hashlib import sha256
import os
import time
from uuid import uuid4

from werkzeug.exceptions import ServiceUnavailable

from app.runtime_config import redis_client


SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - ARGV[2])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 1 end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 0
"""


@lru_cache(maxsize=4)
def _client(url):
    return redis_client(url)


def shared_rate_limited(key, limit, window, now=None):
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    namespace = os.getenv("MONGO_DBNAME", "odcdb")
    digest = sha256(key.encode()).hexdigest()
    try:
        return bool(_client(url).eval(
            SCRIPT, 1, f"odc:{namespace}:rate:{digest}",
            time.time() if now is None else now, window, limit, uuid4().hex,
        ))
    except Exception as error:
        raise ServiceUnavailable("Protection des acces temporairement indisponible") from error
