"""Thread-safe candidate access control for online tests."""

from collections import defaultdict
from datetime import datetime, timedelta
import logging
from queue import Full, Queue
import threading
import time

from bson import ObjectId
from bson.errors import InvalidId

from app.models.candidature import Candidature
from app.models.test import ConnectionLog, Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult


logger = logging.getLogger(__name__)


class TestAccessError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class SlidingWindowRateLimiter:
    def __init__(self, limit=5, window=60, max_keys=10000):
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self.attempts = defaultdict(list)
        self.lock = threading.Lock()

    def is_limited(self, key, now=None):
        now = now or time.time()
        with self.lock:
            self._cleanup(now)
            recent = [
                attempt
                for attempt in self.attempts[key]
                if now - attempt < self.window
            ]
            self.attempts[key] = recent
            if len(recent) >= self.limit:
                return True
            recent.append(now)
            return False

    def _cleanup(self, now):
        if len(self.attempts) <= self.max_keys:
            return
        stale = [
            key
            for key, attempts in self.attempts.items()
            if not attempts or now - attempts[-1] >= self.window
        ]
        for key in stale:
            self.attempts.pop(key, None)


class ExpiringTestCache:
    def __init__(self, ttl=30):
        self.ttl = ttl
        self.values = {}
        self.lock = threading.Lock()

    def get(self, test_id):
        now = time.time()
        key = str(test_id)
        with self.lock:
            self._cleanup(now)
            cached = self.values.get(key)
            if cached and now - cached["timestamp"] < self.ttl:
                return cached["value"]

        test = Test.objects(id=test_id).only(
            "id",
            "title",
            "referentiel",
            "scheduledDate",
            "scheduledTime",
            "duration",
            "totalQuestions",
            "status",
        ).first()
        if test:
            with self.lock:
                self.values[key] = {
                    "value": test,
                    "timestamp": now,
                }
        return test

    def _cleanup(self, now):
        expired = [
            key
            for key, cached in self.values.items()
            if now - cached["timestamp"] >= self.ttl
        ]
        for key in expired:
            self.values.pop(key, None)


class AsyncAccessLogger:
    def __init__(self, maxsize=5000):
        self.queue = Queue(maxsize=maxsize)
        self.start_lock = threading.Lock()
        self.started = False

    def enqueue(self, payload):
        self._start()
        try:
            self.queue.put_nowait(payload)
        except Full:
            logger.warning(
                "Access log queue full for test_id=%s",
                payload.get("test_id"),
            )

    def _start(self):
        if self.started:
            return
        with self.start_lock:
            if self.started:
                return
            thread = threading.Thread(
                target=self._worker,
                daemon=True,
                name="test-access-log-worker",
            )
            thread.start()
            self.started = True

    def _worker(self):
        while True:
            payload = self.queue.get()
            try:
                self._persist(payload)
            except Exception as error:
                logger.warning(
                    "Access log error test_id=%s error=%s",
                    payload.get("test_id"),
                    error,
                )
            finally:
                self.queue.task_done()

    @staticmethod
    def _persist(payload):
        if payload.get("status") != "success":
            logger.warning(
                "Access denied test_id=%s email=%s ip=%s reason=%s",
                payload.get("test_id"),
                payload.get("email"),
                payload.get("ip"),
                payload.get("reason"),
            )
            return
        test = Test.objects(id=payload.get("test_id")).first()
        if not test:
            return
        test.connectionLogs.append(ConnectionLog(
            email=payload.get("email") or "unknown",
            candidateId=payload.get("candidate_id"),
            connectedAt=datetime.utcnow(),
            status="connected",
        ))
        test.totalConnections = (test.totalConnections or 0) + 1
        test.save()


class TestAccessService:
    def __init__(self, rate_limiter=None, cache=None, access_logger=None):
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter()
        self.cache = cache or ExpiringTestCache()
        self.access_logger = access_logger or AsyncAccessLogger()

    def verify(self, test_id, email, phone, ip):
        email = (email or "").strip().lower()
        phone = (phone or "").strip()
        if self.rate_limiter.is_limited(f"{ip}:{email or 'unknown'}"):
            raise TestAccessError(
                "⏳ Trop de tentatives, réessayez plus tard",
                429,
            )
        if not email or not phone:
            self._deny(test_id, email, ip, "missing_fields")
            raise TestAccessError("Email et numéro requis", 400)
        try:
            test_object_id = ObjectId(test_id)
        except InvalidId as error:
            self._deny(test_id, email, ip, "invalid_test_id")
            raise TestAccessError(
                "Identifiant de test invalide",
                400,
            ) from error

        test = self.cache.get(test_object_id)
        if not test:
            self._deny(test_id, email, ip, "test_not_found")
            raise TestAccessError("Test non trouvé", 404)

        candidature = Candidature.objects(email=email).only(
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
        ).first()
        if not candidature or not candidature.phone:
            self._deny(test_id, email, ip, "email_not_found")
            raise TestAccessError("Email ou numéro incorrect", 403)

        stored_phone = self.normalize_digits(candidature.phone)
        incoming_phone = self.normalize_digits(phone)
        if (
            stored_phone != incoming_phone
            and not stored_phone.endswith(incoming_phone)
        ):
            self._deny(test_id, email, ip, "phone_mismatch")
            raise TestAccessError("Numéro incorrect", 403)

        if TestResult.objects(
            testId=str(test.id),
            candidate__email=email,
        ).only("id").first():
            self._deny(test_id, email, ip, "already_passed")
            raise TestAccessError("Test déjà passé", 403)

        group = TestGroup.objects(test_id=test_id).only(
            "candidate_ids",
            "formation",
        ).first()
        if not group:
            self._deny(test_id, email, ip, "group_not_found")
            raise TestAccessError("Groupe du test non trouvé", 404)

        candidate_ids = {
            str(candidate_id)
            for candidate_id in group.candidate_ids or []
        }
        if (
            str(candidature.id) not in candidate_ids
            or self._normalize(group.formation)
            != self._normalize(test.referentiel)
        ):
            self._deny(test_id, email, ip, "not_in_group")
            raise TestAccessError(
                "Vous ne faites pas partie du groupe autorisé "
                "pour ce test",
                403,
            )

        self._validate_time_window(test)
        self.access_logger.enqueue({
            "status": "success",
            "email": email,
            "test_id": str(test.id),
            "candidate_id": str(candidature.id),
            "ip": ip,
        })
        return {
            "candidate": {
                "id": str(candidature.id),
                "firstName": candidature.first_name,
                "lastName": candidature.last_name,
                "email": candidature.email,
            },
            "test": {
                "id": str(test.id),
                "title": test.title,
                "referentiel": test.referentiel,
            },
        }

    def get_public_metadata(self, test_id):
        test = self.cache.get(test_id)
        if not test:
            raise TestAccessError("Test non trouvé", 404)
        return {
            "id": str(test.id),
            "title": test.title,
            "referentiel": test.referentiel,
            "duration": test.duration,
            "scheduledDate": test.scheduledDate,
            "scheduledTime": test.scheduledTime,
            "totalQuestions": (
                test.totalQuestions or len(test.questions or [])
            ),
            "status": test.status,
        }

    @staticmethod
    def update_status(test_id):
        test = Test.objects(id=test_id).first()
        if not test:
            raise TestAccessError("Test non trouvé", 404)
        try:
            start = datetime.strptime(
                f"{test.scheduledDate} {test.scheduledTime}",
                "%Y-%m-%d %H:%M",
            )
            end = start + timedelta(minutes=test.duration)
        except Exception as error:
            raise RuntimeError(
                f"Erreur lors du parsing de la date : {error}"
            ) from error
        if datetime.now() > end and test.status != "completed":
            test.status = "completed"
            test.updatedAt = datetime.utcnow()
            test.save()
            return (
                'Statut du test mis à jour à "terminé"',
                "completed",
            )
        return "Le test est toujours en cours", test.status

    def _validate_time_window(self, test):
        if not (
            test.scheduledDate
            and test.scheduledTime
            and test.duration
        ):
            return
        try:
            start = datetime.strptime(
                f"{test.scheduledDate} {test.scheduledTime}",
                "%Y-%m-%d %H:%M",
            )
            end = start + timedelta(minutes=int(test.duration))
            if not start <= datetime.now() <= end:
                raise TestAccessError("Test non accessible", 403)
        except TestAccessError:
            raise
        except Exception as error:
            logger.error("Test time window error: %s", error)

    def _deny(self, test_id, email, ip, reason):
        self.access_logger.enqueue({
            "status": "failed",
            "email": email,
            "test_id": test_id,
            "reason": reason,
            "ip": ip,
        })

    @staticmethod
    def normalize_digits(value):
        return "".join(
            character
            for character in (value or "")
            if character.isdigit()
        )

    @staticmethod
    def _normalize(value):
        return (value or "").strip().lower()
