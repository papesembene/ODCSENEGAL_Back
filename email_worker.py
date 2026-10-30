"""Dedicated email delivery process; run separately from the API."""

import logging
import os
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
        heartbeat = Path(os.getenv(
            "ODC_EMAIL_HEARTBEAT_FILE",
            str(Path(tempfile.gettempdir(), "odc-email-worker-heartbeat")),
        ))
        while not stopping:
            stop_file = os.getenv("ODC_EMAIL_STOP_FILE")
            if stop_file and Path(stop_file).is_file():
                break
            try:
                heartbeat.touch()
                processed = queue.run_once()
                heartbeat.touch()
                time.sleep(interval if processed else 2)
            except Exception:
                logging.exception("Worker email temporairement indisponible")
                time.sleep(5)


if __name__ == "__main__":
    main()
