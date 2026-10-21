"""Validated environment settings shared by API and worker processes."""

import os


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
