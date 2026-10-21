"""Logging, request tracing and health endpoints."""

from datetime import datetime, timezone
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import socket
import time
import uuid

from flask import Response, abort, g, has_request_context, request
from mongoengine.connection import get_db
from app.runtime_config import redis_client

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
except ImportError:  # pragma: no cover - dependency is installed in deploy env
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
    Counter = Gauge = Histogram = None
    generate_latest = None


REQUEST_COUNT = (
    Counter(
        "odc_http_requests_total",
        "Total HTTP requests processed by the ODC backend.",
        ["method", "endpoint", "status"],
    )
    if Counter
    else None
)
REQUEST_LATENCY = (
    Histogram(
        "odc_http_request_duration_seconds",
        "HTTP request duration in seconds.",
        ["method", "endpoint", "status"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
    )
    if Histogram
    else None
)
MONGODB_UP = (
    Gauge(
        "odc_mongodb_up",
        "MongoDB availability. 1 means reachable, 0 means unavailable.",
    )
    if Gauge
    else None
)
HEALTH_STATUS = (
    Gauge(
        "odc_backend_health",
        "Backend health status. 1 means healthy, 0 means degraded.",
    )
    if Gauge
    else None
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process_id": os.getpid(),
            "thread_name": record.threadName,
        }
        for key in (
            "request_id",
            "client_ip",
            "http_method",
            "endpoint",
            "status_code",
            "response_time_ms",
            "test_id",
            "candidate_email",
            "candidate_phone",
            "test_session_status",
            "idempotent",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, "request_id", None)
            record.client_ip = getattr(g, "client_ip", None)
            record.http_method = request.method
            record.endpoint = request.path
        return True


def configure_observability(app):
    log_dir = os.getenv("LOG_DIR", "logs")
    logger = _configure_logging(log_dir)
    apm_enabled = _configure_apm(app, logger)
    ignored_paths = {"/health", "/metrics", "/favicon.ico"}

    @app.before_request
    def start_request_trace():
        g.request_id = request.headers.get("X-Request-ID") or str(
            uuid.uuid4()
        )
        g.client_ip = _client_ip()
        g.request_started_at = time.perf_counter()
        if request.path not in ignored_paths:
            logger.info(
                "Requête entrante",
                extra={
                    "http_method": request.method,
                    "endpoint": request.path,
                },
            )

    @app.after_request
    def finish_request_trace(response):
        duration = (
            time.perf_counter()
            - getattr(g, "request_started_at", time.perf_counter())
        )
        duration_ms = duration * 1000
        response.headers["X-Request-ID"] = getattr(
            g,
            "request_id",
            "",
        )
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
        _record_http_metrics(response.status_code, duration)
        if request.path not in ignored_paths:
            level = (
                logging.ERROR
                if response.status_code >= 500
                else logging.WARNING
                if response.status_code >= 400
                else logging.INFO
            )
            logger.log(
                level,
                "Réponse HTTP",
                extra={
                    "http_method": request.method,
                    "endpoint": request.path,
                    "status_code": response.status_code,
                    "response_time_ms": round(duration_ms, 2),
                },
            )
        return response

    @app.route("/health", methods=["GET"])
    def health_check():
        mongo_status = _mongo_status()
        dependencies = {"mongodb": mongo_status}
        if os.getenv("REDIS_URL"):
            try:
                with redis_client() as client:
                    client.ping()
                dependencies["redis"] = {"status": "up"}
            except Exception:
                dependencies["redis"] = {"status": "down"}
        healthy = all(value["status"] == "up" for value in dependencies.values())
        if HEALTH_STATUS:
            HEALTH_STATUS.set(1 if healthy else 0)
        return {
            "status": "healthy" if healthy else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "candidatures-api",
            "version": os.getenv("APP_VERSION", "1.0.0"),
            "hostname": socket.gethostname(),
            "environment": app.config.get(
                "ENVIRONMENT",
                "development",
            ),
            "apm_enabled": apm_enabled,
            "dependencies": dependencies,
        }, 200 if healthy else 503

    @app.route("/metrics", methods=["GET"])
    def metrics():
        _authorize_metrics()
        mongo_status = _mongo_status()
        if HEALTH_STATUS:
            HEALTH_STATUS.set(1 if mongo_status["status"] == "up" else 0)
        if generate_latest is None:
            return Response(
                "# prometheus_client_missing 1\n",
                mimetype=CONTENT_TYPE_LATEST,
                status=503,
            )
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    return logger


def _configure_logging(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("candidatures_api")
    logger.setLevel(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )
    logger.propagate = False
    if logger.handlers:
        return logger

    context_filter = RequestContextFilter()
    json_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "app.json.log"),
        when="midnight",
        backupCount=30,
        encoding="utf-8",
        utc=True,
    )
    json_handler.setFormatter(JsonFormatter())
    json_handler.addFilter(context_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s - %(message)s"
        )
    )
    console_handler.addFilter(context_filter)

    logger.addHandler(json_handler)
    logger.addHandler(console_handler)
    return logger


def _configure_apm(app, logger):
    if not (
        os.getenv("ELASTIC_APM_SERVER_URL")
        and os.getenv("ELASTIC_APM_SERVICE_NAME")
    ):
        return False
    try:
        from elasticapm.contrib.flask import ElasticAPM

        ElasticAPM(app)
        return True
    except Exception:
        logger.exception("Initialisation Elastic APM impossible")
        return False


def _client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.headers.get("X-Real-IP") or request.remote_addr


def _record_http_metrics(status_code, duration_seconds):
    if not REQUEST_COUNT or not REQUEST_LATENCY:
        return
    endpoint = request.url_rule.rule if request.url_rule else "unmatched"
    labels = {
        "method": request.method,
        "endpoint": endpoint,
        "status": str(status_code),
    }
    REQUEST_COUNT.labels(**labels).inc()
    REQUEST_LATENCY.labels(**labels).observe(duration_seconds)


def _mongo_status():
    started_at = time.perf_counter()
    try:
        get_db().command("ping")
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        if MONGODB_UP:
            MONGODB_UP.set(1)
        return {"status": "up", "latency_ms": latency_ms}
    except Exception as error:
        if MONGODB_UP:
            MONGODB_UP.set(0)
        return {"status": "down", "error": "MongoDB indisponible"}


def _authorize_metrics():
    expected_token = os.getenv("METRICS_TOKEN")
    if not expected_token:
        return

    bearer = request.headers.get("Authorization", "")
    header_token = request.headers.get("X-Metrics-Token", "")
    provided_token = (
        bearer.removeprefix("Bearer ").strip()
        if bearer.startswith("Bearer ")
        else header_token.strip()
    )
    if provided_token != expected_token:
        abort(401)
