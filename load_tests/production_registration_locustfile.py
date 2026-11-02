"""Bounded production registration load test using synthetic candidates only.

The email worker must be paused before running this against production.
Each Locust user submits at most one candidate. The run ID is embedded in
email and identity fields so those records and their queued emails can be
removed exactly after the test.
"""

from itertools import count
import json
import logging
import os
from pathlib import Path
import re
from threading import Lock
from urllib.parse import urlparse

from gevent.event import Event
from gevent.lock import Semaphore
from locust import HttpUser, between, task
from locust.exception import StopUser


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


def _save_result(result):
    with _result_lock:
        with RESULT_FILE.open("a", encoding="utf-8") as output:
            output.write(json.dumps(result, ensure_ascii=True) + "\n")


class ProductionRegistrationUser(HttpUser):
    # A candidate submits only once; this is a bounded write test, not a loop.
    wait_time = between(0.2, 0.5)

    def on_start(self):
        global _base_url_checked, _burst_ready
        parsed = urlparse(self.host or "")
        if parsed.scheme != "https" or parsed.netloc.lower() != "api.orangedigitalcenter.sn":
            raise RuntimeError("This test is restricted to the production API hostname.")
        if not _base_url_checked:
            _base_url_checked = True

        self.index = next(_indices)
        if self.index > MAX_SIGNUPS:
            raise StopUser()

        self.email = f"load-{RUN_ID}-{self.index}@example.invalid"
        self.identity = f"LOADTEST-{RUN_ID}-{self.index}"
        # Unique synthetic 9-digit values; candidature phone is not a unique DB index.
        self.phone = str(700_000_000 + self.index)
        try:
            response = self.client.get(
                "/api/candidature/status",
                params={"formation": FORMATION},
                name="GET /api/candidature/status (preflight)",
                timeout=10,
            )
            body = response.json()
            if response.status_code != 200 or body.get("data", {}).get("isOpen") is not True:
                LOGGER.error("Campaign is not open; no candidate was submitted.")
                raise StopUser()
        except (ValueError, OSError) as error:
            LOGGER.error("Production campaign preflight failed: %s", error)
            raise StopUser() from error
        if SYNC_BURST:
            with _burst_lock:
                _burst_ready += 1
                release_burst = _burst_ready >= MAX_SIGNUPS
            if release_burst:
                _burst_gate.set()
            if not _burst_gate.wait(timeout=60):
                LOGGER.error("Not all synthetic users reached the burst gate; no candidate was submitted.")
                raise StopUser()

    @task
    def submit_one_synthetic_candidate(self):
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
                if (
                    response.status_code == 201
                    and record["candidature_id"]
                    and record["email_status"] == "queued"
                ):
                    response.success()
                else:
                    response.failure(f"Inscription refusée (HTTP {response.status_code}).")
                _save_result(record)
        finally:
            raise StopUser()
