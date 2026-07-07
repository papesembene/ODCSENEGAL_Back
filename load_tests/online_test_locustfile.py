"""Load scenarios for the online-test candidate journey.

The default scenario is safe: it verifies access and reads public metadata.
Submitting results is opt-in to avoid polluting real test data by accident.
"""

import csv
import itertools
import os
import threading
from datetime import datetime

from locust import HttpUser, between, events, task


TEST_ID = os.getenv("ODC_LOAD_TEST_ID", "").strip()
CANDIDATES_CSV = os.getenv("ODC_LOAD_CANDIDATES_CSV", "").strip()
SUBMIT_RESULTS = os.getenv("ODC_LOAD_SUBMIT_RESULTS", "0") == "1"
SCORE = int(os.getenv("ODC_LOAD_SCORE", "100"))
PASSING_SCORE = int(os.getenv("ODC_LOAD_PASSING_SCORE", "70"))

_candidate_lock = threading.Lock()
_candidate_cycle = None
_candidate_count = 0


def _load_candidates(path):
    with open(path, newline="", encoding="utf-8") as csv_file:
        rows = [
            {
                "name": (row.get("name") or row.get("nom") or "").strip(),
                "email": (row.get("email") or "").strip().lower(),
                "phone": (row.get("phone") or row.get("telephone") or "").strip(),
            }
            for row in csv.DictReader(csv_file)
        ]

    candidates = [
        row
        for row in rows
        if row["email"] and row["phone"]
    ]
    if not candidates:
        raise RuntimeError(
            "Aucun candidat valide. CSV attendu: name,email,phone"
        )
    return candidates


def _next_candidate():
    with _candidate_lock:
        return next(_candidate_cycle).copy()


@events.init.add_listener
def validate_load_context(environment, **kwargs):
    global _candidate_cycle, _candidate_count

    if not TEST_ID:
        raise RuntimeError(
            "Variable ODC_LOAD_TEST_ID manquante pour le test de charge."
        )
    if not CANDIDATES_CSV:
        raise RuntimeError(
            "Variable ODC_LOAD_CANDIDATES_CSV manquante."
        )

    candidates = _load_candidates(CANDIDATES_CSV)
    _candidate_count = len(candidates)
    _candidate_cycle = itertools.cycle(candidates)
    environment.events.request.fire(
        request_type="LOAD",
        name=f"candidates_csv rows={_candidate_count}",
        response_time=0,
        response_length=0,
        exception=None,
        context={},
    )


class OnlineTestCandidateUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.candidate = _next_candidate()
        self.submitted = False
        self.test_metadata = {
            "title": "Test de charge",
            "referentiel": "Non renseigne",
            "passingScore": PASSING_SCORE,
        }
        self.read_public_metadata()

    @task(2)
    def read_public_metadata(self):
        with self.client.get(
            f"/api/admin/tests/{TEST_ID}/public",
            name="GET /api/admin/tests/:id/public",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
                return

            payload = response.json()
            if not payload.get("success"):
                response.failure(payload.get("error") or "metadata invalide")
                return

            data = payload.get("data") or {}
            self.test_metadata = {
                "title": data.get("title") or self.test_metadata["title"],
                "referentiel": data.get("referentiel")
                or self.test_metadata["referentiel"],
                "passingScore": data.get("passingScore") or PASSING_SCORE,
            }

    @task(5)
    def verify_access(self):
        with self.client.post(
            f"/api/admin/tests/{TEST_ID}/verify-access",
            json={
                "email": self.candidate["email"],
                "phone": self.candidate["phone"],
            },
            name="POST /api/admin/tests/:id/verify-access",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                error = _extract_error(response)
                response.failure(error or f"HTTP {response.status_code}")
                return

            payload = response.json()
            if not payload.get("authorized"):
                response.failure(payload.get("error") or "acces refuse")

    @task(1)
    def submit_result(self):
        if not SUBMIT_RESULTS or self.submitted:
            return

        now = datetime.now()
        payload = {
            "testId": TEST_ID,
            "testTitle": self.test_metadata["title"],
            "referentiel": self.test_metadata["referentiel"],
            "candidate": self.candidate,
            "answers": {},
            "score": SCORE,
            "passingScore": self.test_metadata["passingScore"],
            "submittedDate": now.strftime("%Y-%m-%d"),
            "submittedTime": now.strftime("%H:%M:%S"),
        }

        with self.client.post(
            "/api/admin/tests/results",
            json=payload,
            name="POST /api/admin/tests/results",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                error = _extract_error(response)
                response.failure(error or f"HTTP {response.status_code}")
                return

            self.submitted = True


def _extract_error(response):
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    return payload.get("error") or payload.get("message")
