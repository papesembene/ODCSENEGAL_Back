"""Dedicated email delivery process; run separately from the API."""

import logging
from pathlib import Path
import signal
import time
import tempfile

from app import create_app
from app.services.email_outbox import EmailOutbox
from app.runtime_config import env_int


def main():
    app = create_app()
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.basicConfig(level=logging.INFO)
    interval = env_int("EMAIL_SEND_INTERVAL_SECONDS", 1, maximum=60)
    with app.app_context():
        queue = EmailOutbox()
        while not stopping:
            try:
                processed = queue.run_once()
                Path(tempfile.gettempdir(), "odc-email-worker-heartbeat").touch()
                time.sleep(interval if processed else 2)
            except Exception:
                logging.exception("Worker email temporairement indisponible")
                time.sleep(5)


if __name__ == "__main__":
    main()
