"""Bounded production registration load test using synthetic candidates only.

The email worker must be paused before running this against production.
Each Locust user first opens its own keep-alive connection, then submits at
most one candidate. The run ID is embedded in email and identity fields so
those records and their queued emails can be removed exactly after the test.
"""

from itertools import count
import json
import logging
import os
from pathlib import Path
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlparse

from gevent.event import Event
from gevent.lock import Semaphore
from locust import HttpUser, between, task
from requests.exceptions import RequestException


LOGGER = logging.getLogger(__name__)
RUN_ID = os.getenv("ODC_LOAD_RUN_ID", "")
if not re.fullmatch(r"[a-f0-9]{8,32}", RUN_ID):
    raise RuntimeError("Set ODC_LOAD_RUN_ID to 8-32 lowercase hex characters.")
if os.getenv("ODC_LOAD_EMAILS_PAUSED") != "YES":
    raise RuntimeError("Pause the production email worker before this test.")

MAX_SIGNUPS = int(os.getenv("ODC_LOAD_MAX_SIGNUPS", "10"))
if not 1 <= MAX_SIGNUPS <= 1000:
    raise RuntimeError("ODC_LOAD_MAX_SIGNUPS must be between 1 and 1000 per run.")
if MAX_SIGNUPS > 100 and os.getenv("ODC_LOAD_ALLOW_LARGE_PROD") != "YES":
    raise RuntimeError(
        "More than 100 production signups requires ODC_LOAD_ALLOW_LARGE_PROD=YES."
    )
SYNC_BURST = os.getenv("ODC_LOAD_SYNC_BURST") == "YES"
if MAX_SIGNUPS > 100 and not SYNC_BURST:
    raise RuntimeError(
        "More than 100 production signups requires ODC_LOAD_SYNC_BURST=YES."
    )

FORMATION = os.getenv("ODC_LOAD_FORMATION", "Dev Web")
RESULT_FILE = Path(
    os.getenv(
        "ODC_LOAD_RESULT_FILE",
        f"load_tests/reports/production-registration-{RUN_ID}.jsonl",
    )
)
RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
_indices = count(1)
_result_lock = Lock()
_base_url_checked = False
_burst_gate = Event()
_burst_lock = Semaphore()
_burst_ready = 0
_burst_aborted = False
_burst_released = False
_burst_deadline = None


def _abort_burst():
    global _burst_aborted
    with _burst_lock:
        if not _burst_released:
            _burst_aborted = True
            _burst_gate.set()


def _wait_for_burst():
    global _burst_ready, _burst_aborted, _burst_released, _burst_deadline
    with _burst_lock:
        if _burst_aborted:
            return False
        now = monotonic()
        if _burst_deadline is None:
            _burst_deadline = now + 60
        # Check the shared deadline before counting a late participant. A timed
        # out user must never remain eligible to release a partial burst.
        if now >= _burst_deadline:
            _burst_aborted = True
            _burst_gate.set()
            return False
        _burst_ready += 1
        if _burst_ready == MAX_SIGNUPS:
            _burst_released = True
            _burst_gate.set()
        remaining = _burst_deadline - now

    _burst_gate.wait(timeout=remaining)
    with _burst_lock:
        if not _burst_released:
            _burst_aborted = True
            _burst_gate.set()
        return _burst_released and not _burst_aborted


def _save_result(result):
    with _result_lock:
        with RESULT_FILE.open("a", encoding="utf-8") as output:
            output.write(json.dumps(result, ensure_ascii=True) + "\n")


class ProductionRegistrationUser(HttpUser):
    # A candidate submits only once; this is a bounded write test, not a loop.
    wait_time = between(0.2, 0.5)

    def on_start(self):
        global _base_url_checked
        parsed = urlparse(self.host or "")
        if parsed.scheme != "https" or parsed.netloc.lower() != "api.orangedigitalcenter.sn":
            raise RuntimeError("This test is restricted to the production API hostname.")
        if not _base_url_checked:
            _base_url_checked = True

        self.index = next(_indices)
        if self.index > MAX_SIGNUPS:
            self.should_submit = False
            return

        self.should_submit = False
        self.submitted = False
        self.email = f"load-{RUN_ID}-{self.index}@example.invalid"
        self.identity = f"LOADTEST-{RUN_ID}-{self.index}"
        # Unique synthetic 9-digit values; candidature phone is not a unique DB index.
        self.phone = str(700_000_000 + self.index)
        try:
            response = self.client.get(
                "/api/candidature/status",
                params={"formation": FORMATION},
                name="GET /api/candidature/status (connection warm-up)",
                timeout=10,
            )
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code != 200 or body.get("data", {}).get("isOpen") is not True:
                if SYNC_BURST:
                    _abort_burst()
                LOGGER.error(
                    "Campaign preflight failed (HTTP %s, error=%s); no candidate was submitted.",
                    response.status_code,
                    getattr(response, "error", None),
                )
                return
        except RequestException as error:
            if SYNC_BURST:
                _abort_burst()
            LOGGER.error("Production campaign preflight failed: %s", error)
            return
        if SYNC_BURST:
            if not _wait_for_burst():
                LOGGER.error("Synthetic burst aborted: a preflight failed or the shared deadline expired; no candidate was submitted.")
                return
        self.should_submit = True

    @task
    def submit_one_synthetic_candidate(self):
        if not self.should_submit or self.submitted:
            return

        payload = {
            "first_name": "TEST-CHARGE",
            "last_name": f"ODC-{RUN_ID}-{self.index}",
            "email": self.email,
            "phone": self.phone,
            "date_of_birth": "2000-01-01",
            "place_of_birth": "Dakar",
            "gender": "male",
            "cni_or_passport_number": self.identity,
            "nationality": "Senegalaise",
            "region_of_residence": "Dakar",
            "computer_skills": True,
            "available_for_10_months": True,
            "desired_training": FORMATION,
            "accept_conditions": True,
        }
        record = {
            "run_id": RUN_ID,
            "index": self.index,
            "email": self.email,
            "identity": self.identity,
        }
        try:
            with self.client.post(
                "/api/candidature/apply",
                json=payload,
                name="POST /api/candidature/apply",
                timeout=20,
                catch_response=True,
            ) as response:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                record["http_status"] = response.status_code
                record["candidature_id"] = body.get("candidature_id")
                record["email_status"] = body.get("email_status")
                request_error = getattr(response, "error", None)
                if request_error:
                    record["request_error"] = str(request_error)
                    response.failure(f"Erreur transport : {request_error}")
                elif (
                    response.status_code == 201
                    and record["candidature_id"]
                    and record["email_status"] == "queued"
                ):
                    response.success()
                else:
                    response.failure(f"Inscription refusée (HTTP {response.status_code}).")
                _save_result(record)
        finally:
            # Keep the Locust user alive but idle. Stopping it makes Locust spawn
            # a replacement, which can exceed MAX_SIGNUPS and flood logs.
            self.submitted = True
