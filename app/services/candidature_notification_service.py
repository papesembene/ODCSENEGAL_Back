"""Queue candidate confirmation and administrator-selected notifications."""

from hashlib import sha256
from html import escape
import json

from bson import ObjectId
from pymongo import UpdateOne

from app.models.candidature import Candidature
from app.models.email_job import EmailJob
from app.services.email_outbox import EmailOutbox


SUBJECTS = {
    "interview_invitation": "Invitation a un entretien - Orange Digital Center",
    "acceptance": "Information sur votre candidature - Orange Digital Center",
    "rejection": "Information sur votre candidature - Orange Digital Center",
    "information": "Information sur votre candidature - Orange Digital Center",
}


class CandidatureNotificationService(EmailOutbox):
    def enqueue_confirmation(self, candidate):
        candidate_id = str(candidate.id)
        dedup = sha256(f"candidature-confirmation:{candidate_id}".encode()).hexdigest()
        now = self.now()
        EmailJob._get_collection().update_one(
            {"dedup_key": dedup},
            {"$setOnInsert": {
                "_id": ObjectId(), "dedup_key": dedup,
                "batch_key": dedup, "kind": "candidature_confirmation",
                "candidate_id": candidate_id,
                "payload": {"email": candidate.email,
                            "first_name": candidate.first_name,
                            "last_name": candidate.last_name},
                "status": "pending", "attempts": 0,
                "created_at": now, "next_attempt_at": now,
            }},
            upsert=True,
        )
        return dedup

    def enqueue_batch(self, data):
        ids = data.get("candidateIds")
        kind = data.get("emailType")
        message = data.get("customMessage", "")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500:
            raise ValueError("Selectionnez entre 1 et 500 candidatures par envoi")
        if any(not isinstance(item, str) or not ObjectId.is_valid(item) for item in ids):
            raise ValueError("Identifiant de candidature invalide")
        if kind not in SUBJECTS:
            raise ValueError("Type d'email invalide")
        if not isinstance(message, str) or len(message) > 5000:
            raise ValueError("Le message doit contenir au maximum 5000 caracteres")
        if kind in {"information", "interview_invitation"} and not message.strip():
            raise ValueError("Renseignez le message a transmettre aux candidats")
        candidates = list(Candidature.objects(id__in=ids).only("id", "email", "first_name", "last_name"))
        if len(candidates) != len(set(ids)):
            raise ValueError("Une candidature selectionnee n'existe plus")
        if not self.transport.is_configured:
            raise ValueError("Service email non configure")
        signature = json.dumps({
            "type": kind, "message": message.strip(),
            "candidates": sorted((str(item.id), item.email) for item in candidates),
        }, ensure_ascii=True, sort_keys=True)
        batch = sha256(signature.encode()).hexdigest()
        now = self.now()
        operations = []
        for candidate in candidates:
            dedup = sha256(f"candidature:{batch}:{candidate.id}".encode()).hexdigest()
            operations.append(UpdateOne({"dedup_key": dedup}, {"$setOnInsert": {
                "_id": ObjectId(), "dedup_key": dedup, "batch_key": batch,
                "kind": "candidature_notification", "candidate_id": str(candidate.id),
                "payload": {"email": candidate.email, "type": kind,
                            "message": message.strip()},
                "status": "pending", "attempts": 0,
                "created_at": now, "next_attempt_at": now,
            }}, upsert=True))
        self._insert_jobs(EmailJob._get_collection(), operations)
        return {"batchId": batch, **self.summarize(EmailJob.objects(
            kind="candidature_notification", batch_key=batch,
        ))}

    @staticmethod
    def query(batch):
        return EmailJob.objects(kind="candidature_notification", batch_key=batch)

    def retry_failed(self, batch):
        self.requeue(self.query(batch))
        return self.summarize(self.query(batch))

    @staticmethod
    def prepare(job, _now):
        candidate = Candidature.objects(id=job.candidate_id).only(
            "email", "first_name", "last_name",
        ).first()
        if not candidate or candidate.email != job.payload["email"]:
            return None
        if job.kind == "candidature_confirmation":
            name = escape(f"{candidate.first_name} {candidate.last_name}")
            html = ("<p>Bonjour " + name + ",</p>"
                    "<p>Nous avons bien reçu votre candidature à Orange Digital Center.</p>"
                    "<p>Votre dossier sera étudié par notre équipe. Merci de votre intérêt.</p>")
            return [candidate.email], "Confirmation de candidature - Orange Digital Center", html
        kind = job.payload["type"]
        if kind not in SUBJECTS:
            return None
        name = escape(f"{candidate.first_name} {candidate.last_name}")
        message = escape(job.payload["message"]).replace("\n", "<br>")
        html = f"<p>Bonjour {name},</p><p>{message}</p><p>Orange Digital Center - Sonatel</p>"
        return [candidate.email], SUBJECTS[kind], html

    @staticmethod
    def on_accepted(_job, _now):
        pass
