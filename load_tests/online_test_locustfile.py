"""Load scenarios for the online-test candidate journey.

The default scenario is safe: it verifies access and reads public metadata.
Submitting results is opt-in to avoid polluting real test data by accident.
"""

import csv
import os
import threading
from datetime import datetime

from gevent import sleep
from locust import HttpUser, between, events, task


TEST_ID = os.getenv("ODC_LOAD_TEST_ID", "").strip()
CANDIDATES_CSV = os.getenv("ODC_LOAD_CANDIDATES_CSV", "").strip()
SUBMIT_RESULTS = os.getenv("ODC_LOAD_SUBMIT_RESULTS", "0") == "1"
SAVE_DRAFT = os.getenv("ODC_LOAD_SAVE_DRAFT", "1") != "0"
SCORE = int(os.getenv("ODC_LOAD_SCORE", "100"))
PASSING_SCORE = int(os.getenv("ODC_LOAD_PASSING_SCORE", "70"))

_candidate_lock = threading.Lock()
_candidates = []
_candidate_index = 0
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
    global _candidate_index

    with _candidate_lock:
        if _candidate_index >= len(_candidates):
            return None
        candidate = _candidates[_candidate_index].copy()
        _candidate_index += 1
        return candidate


@events.init.add_listener
def validate_load_context(environment, **kwargs):
    global _candidates, _candidate_count, _candidate_index

    if not TEST_ID:
        raise RuntimeError(
            "Variable ODC_LOAD_TEST_ID manquante pour le test de charge."
        )
    if not CANDIDATES_CSV:
        raise RuntimeError(
            "Variable ODC_LOAD_CANDIDATES_CSV manquante."
        )

    _candidates = _load_candidates(CANDIDATES_CSV)
    _candidate_count = len(_candidates)
    _candidate_index = 0
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
        self.completed = False
        self.submitted = False
        self.test_metadata = {
            "title": "Test de charge",
            "referentiel": "Non renseigne",
            "passingScore": PASSING_SCORE,
            "duration": 60,
            "questions": [],
        }

    @task
    def run_candidate_flow(self):
        if self.completed or not self.candidate:
            sleep(60)
            return

        self.read_public_metadata()
        if not self.verify_access():
            self.completed = True
            return
        if SAVE_DRAFT:
            self.save_draft()
        self.submit_result()
        self.completed = True

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
                "duration": data.get("duration") or self.test_metadata["duration"],
                "questions": data.get("questions") or [],
            }

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
                return False
            return True

    def save_draft(self):
        with self.client.put(
            f"/api/admin/tests/{TEST_ID}/session-draft",
            json={
                "email": self.candidate["email"],
                "phone": self.candidate["phone"],
                "name": self.candidate["name"],
                "answers": _build_answers(self.test_metadata.get("questions") or []),
                "lastQuestion": 0,
                "remainingTime": int(self.test_metadata.get("duration") or 60) * 60,
            },
            name="PUT /api/admin/tests/:id/session-draft",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                error = _extract_error(response)
                response.failure(error or f"HTTP {response.status_code}")
                return

            payload = response.json()
            if not payload.get("success"):
                response.failure(payload.get("error") or "draft invalide")

    def submit_result(self):
        if not SUBMIT_RESULTS or self.submitted:
            return

        now = datetime.now()
        payload = {
            "testId": TEST_ID,
            "testTitle": self.test_metadata["title"],
            "referentiel": self.test_metadata["referentiel"],
            "candidate": self.candidate,
            "answers": _build_answers(self.test_metadata.get("questions") or []),
            "score": SCORE,
            "passingScore": self.test_metadata["passingScore"],
            "totalQuestions": len(self.test_metadata.get("questions") or []),
            "answeredQuestions": len(self.test_metadata.get("questions") or []),
            "completedAt": now.isoformat(),
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


def _build_answers(questions):
    answers = {}
    for index, question in enumerate(questions):
        if question.get("type") == "qcm_multiple":
            answers[str(index)] = question.get("correctAnswers") or []
        elif question.get("type") == "texte_libre":
            answers[str(index)] = "Réponse simulée par test de charge"
        else:
            answers[str(index)] = question.get("correctAnswer", 0)
    return answers
