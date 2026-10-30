"""Validated environment settings shared by API and worker processes."""

import os
from pathlib import Path

from dotenv import load_dotenv


def load_runtime_environment():
    """Load one env file, preserving settings supplied by the service."""
    explicit = os.getenv("ODC_ENV_FILE")
    path = Path(explicit) if explicit else Path(__file__).resolve().parents[1] / ".env"
    if explicit and not path.is_file():
        raise RuntimeError("ODC_ENV_FILE introuvable: demarrage refuse")
    # Windows editors may save UTF-8 files with a BOM.
    load_dotenv(path, override=False, encoding="utf-8-sig")


def env_int(name, default, minimum=1, maximum=100000):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} doit etre un entier") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} doit etre compris entre {minimum} et {maximum}")
    return value


def redis_client(url=None):
    from redis import Redis

    return Redis.from_url(
        url or os.environ["REDIS_URL"],
        socket_connect_timeout=3, socket_timeout=3,
        health_check_interval=30,
    )
