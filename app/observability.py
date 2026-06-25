"""Logging, request tracing and health endpoints."""

from datetime import datetime, timezone
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import socket
import time
import uuid

from flask import g, has_request_context, request


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
    ignored_paths = {"/health", "/favicon.ico"}

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
        ) * 1000
        response.headers["X-Request-ID"] = getattr(
            g,
            "request_id",
            "",
        )
        response.headers["X-Response-Time"] = f"{duration:.2f}ms"
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
                    "response_time_ms": round(duration, 2),
                },
            )
        return response

    @app.route("/health", methods=["GET"])
    def health_check():
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "candidatures-api",
            "version": os.getenv("APP_VERSION", "1.0.0"),
            "hostname": socket.gethostname(),
            "environment": app.config.get(
                "ENVIRONMENT",
                "development",
            ),
            "apm_enabled": apm_enabled,
        }

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
