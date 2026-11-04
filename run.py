"""Production entrypoint for the ODC backend."""

import ctypes
import logging
import os
import socket

from waitress import create_server
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.observability import configure_observability


app = create_app()

if os.getenv("TRUST_PROXY_HEADERS", "true").lower() == "true":
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
    )

logger = configure_observability(app)


def _listen_windows(listener, backlog):
    # SOMAXCONN_HINT(N) is -N. Python's socket.listen() normalizes negative
    # values to zero, so the first listen must call WinSock directly.
    winsock = ctypes.WinDLL("Ws2_32")
    winsock.listen.argtypes = (ctypes.c_size_t, ctypes.c_int)
    winsock.listen.restype = ctypes.c_int
    winsock.WSAGetLastError.argtypes = ()
    winsock.WSAGetLastError.restype = ctypes.c_int
    if winsock.listen(listener.fileno(), -backlog) != 0:
        code = winsock.WSAGetLastError()
        raise OSError(code, f"Windows listen failed for backlog {backlog}")


def run_server():
    # Containers must listen on their interface; Windows NSSM sets HOST=127.0.0.1.
    host = os.getenv("HOST", "0.0.0.0")  # nosec B104
    port = int(os.getenv("PORT", "5000"))
    threads = int(os.getenv("WAITRESS_THREADS", "8"))
    timeout = int(os.getenv("WAITRESS_CHANNEL_TIMEOUT", "120"))
    connection_limit = int(
        os.getenv("WAITRESS_CONNECTION_LIMIT", "500" if os.name == "nt" else "1000")
    )
    if os.name == "nt":
        # Waitress counts its listener and trigger in the same socket map.
        # Keep that map below Windows select()'s 512-socket limit.
        connection_limit = min(connection_limit, 500)
    backlog = int(os.getenv("WAITRESS_BACKLOG", "2048" if os.name == "nt" else "1024"))
    if os.name == "nt" and not 200 <= backlog <= 65535:
        raise ValueError("WAITRESS_BACKLOG must be between 200 and 65535 on Windows.")
    max_body_size = int(
        os.getenv(
            "WAITRESS_MAX_REQUEST_BODY_SIZE",
            str(260 * 1024 * 1024),
        )
    )
    logger.info(
        "Démarrage du serveur %s:%s, threads=%s, connection_limit=%s, backlog=%s",
        host,
        port,
        threads,
        connection_limit,
        backlog,
    )
    server = create_server(
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
        backlog=backlog,
        **({"_start": False} if os.name == "nt" else {}),
    )
    try:
        if os.name == "nt":
            listener = getattr(server, "socket", None)
            if listener is None:
                raise RuntimeError("Windows requires one listening socket; configure HOST as a single IPv4 address.")
            # WinSock ignores backlog changes after the first listen.
            _listen_windows(listener, backlog)
            server.accept_connections()
        server.run()
    finally:
        server.close()


if __name__ == "__main__":
    try:
        run_server()
    except KeyboardInterrupt:
        logger.info("Arrêt manuel du serveur")
    except Exception:
        logger.exception("Crash du serveur")
        raise
