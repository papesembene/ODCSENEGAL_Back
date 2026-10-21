"""Queue bounded result notifications using server-side recipients only."""

from hashlib import sha256
from html import escape
import json
import re

from bson import ObjectId
from pymongo import UpdateOne

from app.models.email_job import EmailJob
from app.models.test_result import TestResult
from app.services.email_outbox import EmailOutbox


SUBJECTS = {
    "interview_invitation": "Invitation a un entretien",
    "acceptance": "Resultat du test : seuil atteint",
    "rejection": "Resultat du test : seuil non atteint",
    "results_notification": "Vos resultats au test",
    "information": "Information sur votre candidature",
}


class ResultNotificationService(EmailOutbox):
    def enqueue(self, data):
        ids = data.get("resultIds")
        kind = data.get("emailType")
        message = data.get("customMessage", "")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500:
            raise ValueError("Selectionnez entre 1 et 500 resultats par envoi")
        if any(not isinstance(item, str) or not ObjectId.is_valid(item) for item in ids):
            raise ValueError("Identifiant de resultat invalide")
        if not isinstance(kind, str) or kind not in SUBJECTS:
            raise ValueError("Type d'email invalide")
        if not isinstance(message, str) or len(message) > 5000:
            raise ValueError("Le message doit contenir au maximum 5000 caracteres")
        if kind in {"information", "interview_invitation"} and not message.strip():
            raise ValueError("Renseignez le message a transmettre aux candidats")
        results = list(TestResult.objects(id__in=ids).only("id", "candidate", "testTitle", "score", "status"))
        if len(results) != len(set(ids)):
            raise ValueError("Un resultat selectionne n'existe plus")
        if kind in {"acceptance", "rejection"}:
            expected = "admis" if kind == "acceptance" else "rejeté"
            if any(result.status != expected for result in results):
                raise ValueError("Le type d'email ne correspond pas aux resultats selectionnes")
        if not self.transport.is_configured:
            raise ValueError("Service email non configure")
        signature = json.dumps({"type": kind, "message": message.strip(), "results": sorted(
            (str(result.id), result.candidate.email, result.score, result.status, result.testTitle) for result in results
        )}, ensure_ascii=True, sort_keys=True)
        batch = sha256(signature.encode()).hexdigest()
        now = self.now()
        operations = []
        for result in results:
            dedup = sha256(f"result:{batch}:{result.id}".encode()).hexdigest()
            operations.append(UpdateOne({"dedup_key": dedup}, {"$setOnInsert": {
                "_id": ObjectId(), "dedup_key": dedup, "batch_key": batch, "kind": "test_result",
                "candidate_id": str(result.id), "payload": {
                    "email": result.candidate.email, "type": kind, "message": message.strip(),
                    "score": result.score, "status": result.status,
                }, "status": "pending", "attempts": 0, "created_at": now, "next_attempt_at": now,
            }}, upsert=True))
        self._insert_jobs(EmailJob._get_collection(), operations)
        return {"batchId": batch, **self.summary(batch)}

    @staticmethod
    def query(batch):
        if not re.fullmatch(r"[0-9a-f]{64}", batch):
            raise ValueError("Identifiant d'envoi invalide")
        return EmailJob.objects(kind="test_result", batch_key=batch)

    @classmethod
    def summary(cls, batch):
        return cls.summarize(cls.query(batch))

    def retry_failed(self, batch):
        self.requeue(self.query(batch))
        return self.summary(batch)

    @staticmethod
    def prepare(job, now):
        result = TestResult.objects(id=job.candidate_id).only("candidate", "score", "status", "testTitle").first()
        payload = job.payload
        if not result or result.candidate.email != payload["email"]:
            return None
        if (result.score, result.status) != (payload["score"], payload["status"]):
            return None  # Do not send an obsolete grade after a manual correction.
        subject = SUBJECTS[payload["type"]]
        html = f"<p>Bonjour {escape(result.candidate.name)},</p><p>{escape(result.testTitle)}</p>"
        if payload["type"] in {"results_notification", "acceptance", "rejection"}:
            html += f"<p>Score au test : {result.score}%.</p><p>Ce resultat ne constitue pas une admission definitive a la formation.</p>"
        if payload["message"]:
            html += "<p>" + escape(payload["message"]).replace("\n", "<br>") + "</p>"
        return [payload["email"]], subject, html

    @staticmethod
    def on_accepted(job, now):
        pass
