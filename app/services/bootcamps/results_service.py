"""Final results of a referential campaign, notified to candidates only when an administrator decides to.

Decisions come from Bootcamps whose coach submitted the results. The administrator validates them,
edits one e-mail per decision, previews it, chooses the recipients and sends. A candidate never receives
the same decision twice; a changed decision may be notified again. Every send keeps the texts used.
"""

from datetime import datetime
from hashlib import sha256
from html import escape

from bson import ObjectId
from mongoengine import Q
from pymongo import UpdateOne

from app.models.bootcamp import Bootcamp, BootcampParticipant
from app.models.candidature import Candidature
from app.models.email_job import EmailJob
from app.models.interview import InterviewCampaign, InterviewEvaluation
from app.services.email_outbox import EmailOutbox
from app.services.interviews.exceptions import InterviewConflictError, InterviewValidationError
from app.services.interviews.ranking_service import _actor
from app.services.interviews.referential_service import ReferentialInterviews


RESULT_KIND = "final_result"
NOTIFIED_DECISIONS = ("retained", "waiting_list", "rejected")
PLACEHOLDERS = ("prenom", "nom", "referentiel", "bootcamp")
DEFAULT_TEMPLATES = {
    "retained": {
        "subject": "Félicitations : vous êtes retenu(e) pour la formation {referentiel}",
        "body": "Bonjour {prenom} {nom},\n\nNous avons le plaisir de vous annoncer que vous êtes retenu(e) pour la formation "
                "{referentiel} à l’issue du Bootcamp {bootcamp}.\n\nVous recevrez prochainement les informations pratiques "
                "sur la rentrée (date, lieu et documents à fournir).\n\nBienvenue à Orange Digital Center !",
    },
    "waiting_list": {
        "subject": "Votre candidature à la formation {referentiel} : liste d’attente",
        "body": "Bonjour {prenom} {nom},\n\nÀ l’issue du Bootcamp {bootcamp}, votre candidature à la formation {referentiel} "
                "est placée sur liste d’attente.\n\nSi une place se libère, nous vous contacterons rapidement. "
                "Merci pour votre engagement tout au long du processus.",
    },
    "rejected": {
        "subject": "Votre candidature à la formation {referentiel}",
        "body": "Bonjour {prenom} {nom},\n\nNous vous remercions pour votre participation au Bootcamp {bootcamp}. "
                "Après délibération, nous ne pouvons malheureusement pas retenir votre candidature pour la formation "
                "{referentiel}.\n\nNous vous encourageons à suivre nos autres programmes et à candidater de nouveau "
                "lors d’une prochaine campagne.",
    },
}


def render(template, values):
    """Fill the placeholders; the HTML version escapes every value and turns paragraphs into <p>."""
    subject, body = template["subject"], template["body"]
    for key in PLACEHOLDERS:
        subject = subject.replace("{" + key + "}", values.get(key, ""))
    html_body = escape(body)
    for key in PLACEHOLDERS:
        html_body = html_body.replace("{" + key + "}", escape(values.get(key, "")))
    paragraphs = [paragraph.replace("\n", "<br>") for paragraph in html_body.split("\n\n") if paragraph.strip()]
    html = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs) + "<p>Orange Digital Center Sénégal</p>"
    return subject.strip(), html


def _templates(value):
    """Validate the three editable e-mails (subject and body for each notified decision)."""
    if not isinstance(value, dict) or set(value) != set(NOTIFIED_DECISIONS):
        raise InterviewValidationError("Renseignez un e-mail pour chaque statut.")
    result = {}
    for decision in NOTIFIED_DECISIONS:
        item = value[decision]
        subject = item.get("subject") if isinstance(item, dict) else None
        body = item.get("body") if isinstance(item, dict) else None
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 200:
            raise InterviewValidationError("Chaque objet d’e-mail est obligatoire (200 caractères au maximum).")
        if not isinstance(body, str) or not body.strip() or len(body) > 5000:
            raise InterviewValidationError("Chaque message est obligatoire (5 000 caractères au maximum).")
        result[decision] = {"subject": subject.strip(), "body": body.strip()}
    return result


class FinalResultsService:
    def __init__(self, referentials=None):
        self.referentials = referentials or ReferentialInterviews()

    def _context(self, formation, campaign_id):
        workspace, training, source = self.referentials._workspace(formation, campaign_id=campaign_id)
        if not workspace or not source:
            raise InterviewValidationError("Aucun entretien organisé pour ce référentiel et cette campagne.")
        bootcamps = {str(item.id): item for item in Bootcamp.objects(formation=training["code"], candidature_campaign_id=str(source.id))}
        participants = list(BootcampParticipant.objects(bootcamp_id__in=list(bootcamps))) if bootcamps else []
        return workspace, training, source, bootcamps, participants

    @staticmethod
    def _fingerprint(bootcamps, participants):
        return sorted([participant.candidate_id, participant.decision] for participant in participants
                      if bootcamps[participant.bootcamp_id].status == "submitted")

    @staticmethod
    def _latest_jobs(workspace_id):
        latest = {}
        for job in EmailJob.objects(kind=RESULT_KIND, batch_key=workspace_id).order_by("created_at").only(
            "candidate_id", "group_id", "status", "created_at", "sent_at", "last_error",
        ):
            latest[job.candidate_id] = job
        return latest

    def get(self, formation, campaign_id=None):
        workspace, training, source, bootcamps, participants = self._context(formation, campaign_id)
        results = workspace.final_results or {}
        candidates = {str(item.id): item for item in Candidature.objects(id__in=[row.candidate_id for row in participants]).only(
            "first_name", "last_name", "email", "phone",
        )} if participants else {}
        jobs = self._latest_jobs(str(workspace.id))
        rows = []
        for participant in participants:
            bootcamp = bootcamps[participant.bootcamp_id]
            candidate = candidates.get(participant.candidate_id)
            job = jobs.get(participant.candidate_id)
            rows.append({
                "candidate_id": participant.candidate_id,
                "first_name": getattr(candidate, "first_name", None), "last_name": getattr(candidate, "last_name", None),
                "email": getattr(candidate, "email", None), "phone": getattr(candidate, "phone", None),
                "bootcamp_id": participant.bootcamp_id, "bootcamp": bootcamp.title, "bootcamp_status": bootcamp.status,
                "decision": participant.decision, "coach_comment": participant.coach_comment,
                "final": bootcamp.status == "submitted",
                "notification": {
                    "decision": job.group_id, "status": job.status, "error": job.last_error,
                    "queued_at": job.created_at.isoformat() + "Z" if job.created_at else None,
                    "sent_at": job.sent_at.isoformat() + "Z" if job.sent_at else None,
                } if job else None,
            })
        rows.sort(key=lambda row: ((row["last_name"] or "").casefold(), (row["first_name"] or "").casefold()))
        submitted = [item for item in bootcamps.values() if item.status == "submitted"]
        validated = results.get("status") == "validated"
        return {
            "formation": training["code"], "title": training["title"], "workspace_id": str(workspace.id),
            "revision": results.get("revision", 0), "status": results.get("status", "draft"),
            "validated_at": results.get("validated_at"), "validated_by": results.get("validated_by"),
            "changed_since_validation": validated and results.get("fingerprint") != self._fingerprint(bootcamps, participants),
            "bootcamps": {"total": len(bootcamps), "submitted": len(submitted),
                          "launched": sum(item.status == "launched" for item in bootcamps.values()),
                          "draft": sum(item.status == "draft" for item in bootcamps.values())},
            "templates": results.get("templates") or DEFAULT_TEMPLATES, "placeholders": list(PLACEHOLDERS),
            "history": results.get("history", []), "rows": rows,
            "emails": EmailOutbox.summarize(EmailJob.objects(kind=RESULT_KIND, batch_key=str(workspace.id))),
        }

    def all_results(self, campaign_id=None):
        """Every Bootcamp participant of every referential for a campaign, for the cross-referential list."""
        rows = []
        for item in self.referentials.overview(campaign_id):
            label = item.get("candidature_campaign")
            if not label:
                continue
            workspace, training, source = self.referentials._workspace(item["formation"], campaign_id=label["id"])
            if not workspace or not source:
                continue
            bootcamps = {str(bootcamp.id): bootcamp for bootcamp in Bootcamp.objects(formation=training["code"], candidature_campaign_id=str(source.id))}
            participants = list(BootcampParticipant.objects(bootcamp_id__in=list(bootcamps))) if bootcamps else []
            if not participants:
                continue
            ids = [participant.candidate_id for participant in participants]
            candidates = {str(candidate.id): candidate for candidate in Candidature.objects(id__in=ids).only(
                "first_name", "last_name", "email", "phone", "gender", "region_of_residence", "education_level", "training_site_name",
            )}
            interviews = {evaluation.candidature_id: evaluation.questionnaire for evaluation in InterviewEvaluation.objects(
                campaign_id=str(workspace.id), candidature_id__in=ids,
            ).only("candidature_id", "questionnaire")}
            jobs = self._latest_jobs(str(workspace.id))
            for participant in participants:
                bootcamp = bootcamps[participant.bootcamp_id]
                candidate = candidates.get(participant.candidate_id)
                questionnaire = interviews.get(participant.candidate_id) or {}
                job = jobs.get(participant.candidate_id)
                rows.append({
                    "candidate_id": participant.candidate_id, "formation": training["code"], "formation_title": training["title"],
                    "first_name": getattr(candidate, "first_name", None), "last_name": getattr(candidate, "last_name", None),
                    "email": getattr(candidate, "email", None), "phone": getattr(candidate, "phone", None),
                    "gender": getattr(candidate, "gender", None), "region": getattr(candidate, "region_of_residence", None),
                    "education_level": getattr(candidate, "education_level", None), "training_site": getattr(candidate, "training_site_name", None),
                    "bootcamp_id": participant.bootcamp_id, "bootcamp": bootcamp.title, "final": bootcamp.status == "submitted",
                    "decision": participant.decision, "coach_comment": participant.coach_comment,
                    "interview_score": (questionnaire.get("scores") or {}).get("global"), "validator_comment": questionnaire.get("comment") or "",
                    "notified": bool(job and job.group_id == participant.decision and job.status == "sent"),
                    "notification_status": job.status if job and job.group_id == participant.decision else None,
                })
        rows.sort(key=lambda row: (row["formation_title"], (row["last_name"] or "").casefold(), (row["first_name"] or "").casefold()))
        return {"rows": rows, "campaigns": self.referentials.overview_campaigns(), "campaign_id": campaign_id}

    @staticmethod
    def _save(workspace, revision, results):
        if type(revision) is not int or revision != (workspace.final_results or {}).get("revision", 0):
            raise InterviewConflictError("Les résultats ont changé. Actualisez avant de recommencer.")
        results["revision"] = revision + 1
        condition = Q(final_results__revision=revision)
        if revision == 0:
            condition |= Q(final_results__revision__exists=False)
        if not InterviewCampaign.objects(condition, id=workspace.id).update_one(set__final_results=results, set__updated_at=datetime.utcnow()):
            raise InterviewConflictError("Les résultats ont changé. Actualisez avant de recommencer.")

    def validate(self, formation, data, admin):
        if not isinstance(data, dict) or data.get("confirmed") is not True:
            raise InterviewValidationError("Confirmez la validation des résultats.")
        workspace, _, _, bootcamps, participants = self._context(formation, data.get("campaign_id"))
        open_bootcamps = [item.title for item in bootcamps.values() if item.status == "launched"]
        if open_bootcamps:
            raise InterviewValidationError("Résultats non soumis par le coach : " + ", ".join(open_bootcamps) + ".")
        if not any(item.status == "submitted" for item in bootcamps.values()):
            raise InterviewValidationError("Aucun Bootcamp n’a encore de résultats soumis par son coach.")
        results = dict(workspace.final_results or {})
        now = datetime.utcnow().isoformat() + "Z"
        actor = _actor(admin)
        fingerprint = self._fingerprint(bootcamps, participants)
        counts = {decision: sum(decision == item[1] for item in fingerprint) for decision in NOTIFIED_DECISIONS}
        results.update(status="validated", validated_at=now, validated_by=actor, fingerprint=fingerprint)
        results["history"] = [*results.get("history", []), {"at": now, "by": actor, "action": "validate", "counts": counts}]
        self._save(workspace, data.get("revision"), results)
        return self.get(formation, data.get("campaign_id"))

    def save_templates(self, formation, data, admin):
        if not isinstance(data, dict):
            raise InterviewValidationError("Modèles invalides.")
        workspace, _, _, _, _ = self._context(formation, data.get("campaign_id"))
        results = dict(workspace.final_results or {})
        results["templates"] = _templates(data.get("templates"))
        results["templates_updated"] = {"at": datetime.utcnow().isoformat() + "Z", "by": _actor(admin)}
        self._save(workspace, data.get("revision"), results)
        return self.get(formation, data.get("campaign_id"))

    def preview(self, formation, data):
        """Render the e-mail exactly as it will be sent, for one candidate or with sample values."""
        if not isinstance(data, dict) or data.get("decision") not in NOTIFIED_DECISIONS:
            raise InterviewValidationError("Choisissez un statut à prévisualiser.")
        workspace, training, _, bootcamps, participants = self._context(formation, data.get("campaign_id"))
        templates = _templates(data["templates"]) if data.get("templates") else (workspace.final_results or {}).get("templates") or DEFAULT_TEMPLATES
        participant = next((item for item in participants if item.candidate_id == data.get("candidate_id")), None) or \
            next((item for item in participants if item.decision == data["decision"]), None)
        candidate = Candidature.objects(id=participant.candidate_id).only("first_name", "last_name", "email").first() if participant else None
        values = {
            "prenom": getattr(candidate, "first_name", None) or "Awa", "nom": getattr(candidate, "last_name", None) or "Diop",
            "referentiel": training["title"], "bootcamp": bootcamps[participant.bootcamp_id].title if participant else "Bootcamp 1",
        }
        subject, html = render(templates[data["decision"]], values)
        return {"subject": subject, "html": html, "to": getattr(candidate, "email", None) or "exemple@example.com",
                "sample": candidate is None}

    def send(self, formation, data, admin):
        """Queue the result e-mail for the chosen candidates; already notified decisions are skipped."""
        if not isinstance(data, dict) or data.get("confirmed") is not True:
            raise InterviewValidationError("Confirmez l’envoi des résultats.")
        workspace, training, _, bootcamps, participants = self._context(formation, data.get("campaign_id"))
        results = dict(workspace.final_results or {})
        if results.get("status") != "validated":
            raise InterviewValidationError("Validez les résultats avant de les envoyer.")
        if results.get("fingerprint") != self._fingerprint(bootcamps, participants):
            raise InterviewConflictError("Des décisions ont changé depuis la validation : validez de nouveau les résultats.")
        wanted = data.get("candidate_ids")
        if not isinstance(wanted, list) or not wanted or len(wanted) > 5000:
            raise InterviewValidationError("Sélectionnez au moins un destinataire.")
        outbox = EmailOutbox()
        if not outbox.transport.is_configured:
            raise InterviewValidationError("Le service d’envoi des e-mails n’est pas configuré.")
        templates = results.get("templates") or DEFAULT_TEMPLATES
        workspace_id = str(workspace.id)
        chosen = [item for item in participants if item.candidate_id in set(wanted)
                  and bootcamps[item.bootcamp_id].status == "submitted" and item.decision in NOTIFIED_DECISIONS]
        candidates = {str(item.id): item for item in Candidature.objects(id__in=[item.candidate_id for item in chosen]).only(
            "first_name", "last_name", "email",
        )}
        now = outbox.now()
        operations, skipped, counts = [], 0, {decision: 0 for decision in NOTIFIED_DECISIONS}
        for participant in chosen:
            candidate = candidates.get(participant.candidate_id)
            if not candidate:
                continue
            key = sha256(f"final:{workspace_id}:{participant.candidate_id}:{participant.decision}".encode()).hexdigest()
            if EmailJob.objects(dedup_key=key).first():
                skipped += 1
                continue
            subject, html = render(templates[participant.decision], {
                "prenom": candidate.first_name or "", "nom": candidate.last_name or "", "referentiel": training["title"],
                "bootcamp": bootcamps[participant.bootcamp_id].title,
            })
            counts[participant.decision] += 1
            operations.append(UpdateOne({"dedup_key": key}, {"$setOnInsert": {
                "dedup_key": key, "batch_key": workspace_id, "kind": RESULT_KIND, "group_id": participant.decision,
                "candidate_id": participant.candidate_id, "status": "pending", "attempts": 0, "created_at": now,
                "next_attempt_at": now, "payload": {"email": candidate.email, "subject": subject, "html": html},
            }}, upsert=True))
        if operations:
            outbox._insert_jobs(EmailJob._get_collection(), operations)
            moment = datetime.utcnow().isoformat() + "Z"
            results["history"] = [*results.get("history", []), {
                "at": moment, "by": _actor(admin), "action": "send", "counts": counts, "skipped": skipped,
                "templates": {decision: templates[decision] for decision, count in counts.items() if count},
            }]
            self._save(workspace, data.get("revision"), results)
        return {"queued": len(operations), "skipped": skipped, "counts": counts}

    def retry(self, formation, data):
        workspace, _, _, _, _ = self._context(formation, (data or {}).get("campaign_id"))
        outbox = EmailOutbox()
        jobs = EmailJob.objects(kind=RESULT_KIND, batch_key=str(workspace.id))
        outbox.requeue(jobs)
        return outbox.summarize(jobs)


class FinalResultOutbox(EmailOutbox):
    @staticmethod
    def prepare(job, _now):
        candidate = Candidature.objects(id=job.candidate_id).only("email").first() if ObjectId.is_valid(job.candidate_id) else None
        payload = job.payload or {}
        if not candidate or candidate.email != payload.get("email"):
            return None
        participant = BootcampParticipant.objects(candidate_id=job.candidate_id).only("decision").first()
        if not participant or participant.decision != job.group_id:
            return None
        return [candidate.email], payload["subject"], payload["html"]

    @staticmethod
    def on_accepted(_job, _now):
        pass
