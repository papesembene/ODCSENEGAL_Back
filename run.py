"""Production entrypoint for the ODC backend."""

import logging
import os
import socket

from dotenv import load_dotenv
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.observability import configure_observability


load_dotenv()
app = create_app()

if os.getenv("TRUST_PROXY_HEADERS", "true").lower() == "true":
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
    )

logger = configure_observability(app)


def run_server():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    threads = int(os.getenv("WAITRESS_THREADS", "150"))
    timeout = int(os.getenv("WAITRESS_CHANNEL_TIMEOUT", "120"))
    connection_limit = int(
        os.getenv("WAITRESS_CONNECTION_LIMIT", "1000")
    )
    max_body_size = int(
        os.getenv(
            "WAITRESS_MAX_REQUEST_BODY_SIZE",
            str(260 * 1024 * 1024),
        )
    )
    logger.info(
        "Démarrage du serveur %s:%s, threads=%s",
        host,
        port,
        threads,
    )
    serve(
        app,
        host=host,
        port=port,
        threads=threads,
        channel_timeout=timeout,
        cleanup_interval=30,
        asyncore_use_poll=True,
        ident=(
            f"candidatures-api-{os.getpid()}-{socket.gethostname()}"
        ),
        max_request_body_size=max_body_size,
        connection_limit=connection_limit,
    )


if __name__ == "__main__":
    try:
        run_server()
    except KeyboardInterrupt:
        logger.info("Arrêt manuel du serveur")
    except Exception:
        logger.exception("Crash du serveur")
        raise
