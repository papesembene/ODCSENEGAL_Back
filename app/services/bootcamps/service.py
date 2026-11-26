"""Bootcamps fed by the validated interview pre-selection, and the coach's manual final decisions.

Admins create Bootcamps per referential and candidature campaign, place the pre-selected candidates
(one Bootcamp per candidate and campaign), then launch them, which queues the invitation e-mails.
Coaches only see their own Bootcamps; they write an appraisal and a decision for each participant,
then submit the results. Results are never sent to candidates from here.
"""

from datetime import date, datetime
from hashlib import sha256
from html import escape

from bson import ObjectId
from mongoengine import NotUniqueError
from pymongo import UpdateOne

from app.models.bootcamp import Bootcamp, BootcampParticipant, FINAL_DECISIONS
from app.models.candidature import Candidature
from app.models.candidature_campaign import CandidatureCampaign
from app.models.email_job import EmailJob
from app.models.interview import InterviewEvaluation
from app.models.user import User
from app.services.email_outbox import EmailOutbox
from app.services.interviews.exceptions import (
    InterviewConflictError, InterviewForbiddenError, InterviewNotFoundError, InterviewValidationError,
)
from app.services.interviews.member_roles import has_role, role_query
from app.services.interviews.ranking_service import _actor
from app.services.interviews.referential_service import ReferentialInterviews
from app.services.trainings.catalog import get_catalog


INVITATION_KIND = "bootcamp_invitation"
DECISION_LABELS = {"pending": "En attente de décision", "retained": "Retenu", "waiting_list": "Liste d’attente", "rejected": "Non retenu"}


def _text(value, label, maximum, *, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise InterviewValidationError(f"{label} doit être du texte.")
    value = value.strip()
    if required and not value:
        raise InterviewValidationError(f"Renseignez {label.lower()}.")
    if len(value) > maximum:
        raise InterviewValidationError(f"{label} : {maximum} caractères au maximum.")
    return value


def _date(value, label):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise InterviewValidationError(f"Indiquez la {label}.") from error


def _name(record):
    return f"{getattr(record, 'first_name', '') or ''} {getattr(record, 'last_name', '') or ''}".strip() or getattr(record, "email", "")


def is_coach(user):
    return has_role(user, "coach")


class BootcampService:
    def __init__(self, referentials=None):
        self.referentials = referentials or ReferentialInterviews()

    # ----- shared helpers -------------------------------------------------------------------------

    def _workspace(self, formation, campaign_id):
        workspace, training, source = self.referentials._workspace(formation, campaign_id=campaign_id)
        if not workspace or not source:
            raise InterviewValidationError("Aucun entretien organisé pour ce référentiel et cette campagne.")
        return workspace, training, source

    @staticmethod
    def _preselected(workspace):
        selection = workspace.preselection or {}
        return list(selection.get("selected", [])) if selection.get("status") == "validated" else []

    @staticmethod
    def _coaches(formation=None, *, include_inactive=False):
        users = User.objects(profile_data__admin_scope="interview_member", __raw__=role_query("coach"))
        if not include_inactive:
            users = users.filter(is_active=True)
        if formation:
            users = users.filter(profile_data__interview_formations=formation)
        return {str(user.id): {"id": str(user.id), "name": _name(user), "email": user.email}
                for user in users.only("id", "first_name", "last_name", "email").order_by("first_name", "last_name")}

    @staticmethod
    def _bootcamp(bootcamp_id):
        bootcamp = Bootcamp.objects(id=bootcamp_id).first() if ObjectId.is_valid(bootcamp_id) else None
        if not bootcamp:
            raise InterviewNotFoundError("Bootcamp introuvable.")
        return bootcamp

    @staticmethod
    def _check_revision(bootcamp, revision):
        if type(revision) is not int or revision != bootcamp.revision:
            raise InterviewConflictError("Le Bootcamp a changé. Actualisez avant de recommencer.")

    @staticmethod
    def _bump(bootcamp, **changes):
        updated = Bootcamp.objects(id=bootcamp.id, revision=bootcamp.revision).update_one(
            inc__revision=1, set__updated_at=datetime.utcnow(), **{f"set__{key}": value for key, value in changes.items()},
        )
        if not updated:
            raise InterviewConflictError("Le Bootcamp a changé. Actualisez avant de recommencer.")

    @staticmethod
    def _candidates(candidate_ids, workspace_id):
        """Candidate identity plus interview score and validator appraisal, by candidate id."""
        details = {str(candidate.id): candidate for candidate in Candidature.objects(id__in=list(candidate_ids)).only(
            "first_name", "last_name", "email", "phone", "education_level", "speciality", "current_structure",
            "region_of_residence", "training_site_name", "date_of_birth",
        )} if candidate_ids else {}
        interviews = {item.candidature_id: item for item in InterviewEvaluation.objects(
            campaign_id=workspace_id, candidature_id__in=list(candidate_ids),
        ).only("candidature_id", "questionnaire")} if candidate_ids else {}
        rows = {}
        for candidate_id in candidate_ids:
            candidate = details.get(candidate_id)
            interview = interviews.get(candidate_id)
            questionnaire = interview.questionnaire if interview else {}
            rows[candidate_id] = {
                "candidate_id": candidate_id,
                "first_name": getattr(candidate, "first_name", None), "last_name": getattr(candidate, "last_name", None),
                "email": getattr(candidate, "email", None), "phone": getattr(candidate, "phone", None),
                "education_level": getattr(candidate, "education_level", None), "speciality": getattr(candidate, "speciality", None),
                "current_structure": getattr(candidate, "current_structure", None),
                "region_of_residence": getattr(candidate, "region_of_residence", None),
                "training_site_name": getattr(candidate, "training_site_name", None),
                "interview_score": (questionnaire.get("scores") or {}).get("global"),
                "interview_scores": questionnaire.get("scores") or {},
                "validator_comment": questionnaire.get("comment") or "",
            }
        return rows

    def _serialize(self, bootcamp, participants, *, coaches, invitations=None):
        counts = {decision: 0 for decision in FINAL_DECISIONS}
        for participant in participants:
            counts[participant.decision] += 1
        return {
            "id": str(bootcamp.id), "title": bootcamp.title, "formation": bootcamp.formation,
            "candidature_campaign_id": bootcamp.candidature_campaign_id, "status": bootcamp.status,
            "coach_ids": bootcamp.coach_ids, "coaches": [coaches.get(coach_id, {"id": coach_id, "name": "Compte indisponible"}) for coach_id in bootcamp.coach_ids],
            "start_date": bootcamp.start_date.isoformat(), "end_date": bootcamp.end_date.isoformat(),
            "location": bootcamp.location, "description": bootcamp.description, "capacity": bootcamp.capacity,
            "participants_count": len(participants), "decisions": counts, "revision": bootcamp.revision,
            "launched_at": bootcamp.launched_at.isoformat() + "Z" if bootcamp.launched_at else None,
            "submitted_at": bootcamp.submitted_at.isoformat() + "Z" if bootcamp.submitted_at else None,
            "submitted_by": bootcamp.submitted_by or None,
            **({"invitations": invitations} if invitations is not None else {}),
        }

    @staticmethod
    def _participant_row(participant, details):
        return {
            **details.get(participant.candidate_id, {"candidate_id": participant.candidate_id}),
            "bootcamp_id": participant.bootcamp_id, "coach_comment": participant.coach_comment,
            "decision": participant.decision,
            "decided_at": participant.decided_at.isoformat() + "Z" if participant.decided_at else None,
            "decided_by": participant.decided_by or None,
        }

    # ----- admin ----------------------------------------------------------------------------------

    def overview(self, campaign_id=None):
        rows = []
        for item in self.referentials.overview(campaign_id):
            workspace, _, source = self.referentials._workspace(item["formation"], campaign_id=item["candidature_campaign"]["id"]) \
                if item.get("candidature_campaign") else (None, None, None)
            preselected = self._preselected(workspace) if workspace else []
            bootcamps = list(Bootcamp.objects(formation=item["formation"], candidature_campaign_id=str(source.id))) if source else []
            participants = list(BootcampParticipant.objects(bootcamp_id__in=[str(bootcamp.id) for bootcamp in bootcamps])) if bootcamps else []
            decisions = {decision: sum(participant.decision == decision for participant in participants) for decision in FINAL_DECISIONS}
            rows.append({
                "formation": item["formation"], "title": item["title"], "candidature_campaign": item.get("candidature_campaign"),
                "preselection_status": ((workspace.preselection or {}).get("status") if workspace else None),
                "preselected": len(preselected), "bootcamps": len(bootcamps),
                "coaches": len({coach for bootcamp in bootcamps for coach in bootcamp.coach_ids}),
                "assigned": len(participants), "retained": decisions["retained"], "waiting_list": decisions["waiting_list"],
                "rejected": decisions["rejected"], "to_evaluate": decisions["pending"],
            })
        return rows

    def detail(self, formation, campaign_id=None):
        workspace, training, source = self._workspace(formation, campaign_id)
        preselected = self._preselected(workspace)
        bootcamps = list(Bootcamp.objects(formation=training["code"], candidature_campaign_id=str(source.id)).order_by("start_date", "created_at"))
        participants = list(BootcampParticipant.objects(candidature_campaign_id=str(source.id), formation=training["code"]))
        by_bootcamp = {}
        for participant in participants:
            by_bootcamp.setdefault(participant.bootcamp_id, []).append(participant)
        details = self._candidates(set(preselected) | {participant.candidate_id for participant in participants}, str(workspace.id))
        coaches = self._coaches(include_inactive=True)
        placed = {participant.candidate_id: participant for participant in participants}
        jobs = EmailJob.objects(kind=INVITATION_KIND, batch_key__in=[str(bootcamp.id) for bootcamp in bootcamps]) if bootcamps else None
        return {
            "formation": training["code"], "title": training["title"], "workspace_id": str(workspace.id),
            "candidature_campaign": self.referentials._campaign_label(source, datetime.utcnow()),
            "preselection_status": (workspace.preselection or {}).get("status"),
            "available_coaches": list(self._coaches(training["code"]).values()),
            "bootcamps": [self._serialize(bootcamp, by_bootcamp.get(str(bootcamp.id), []), coaches=coaches,
                                          invitations=EmailOutbox.summarize(jobs.filter(batch_key=str(bootcamp.id))))
                          for bootcamp in bootcamps],
            "candidates": [
                {**details[candidate_id], "bootcamp_id": placed[candidate_id].bootcamp_id if candidate_id in placed else None,
                 "decision": placed[candidate_id].decision if candidate_id in placed else None,
                 "coach_comment": placed[candidate_id].coach_comment if candidate_id in placed else ""}
                for candidate_id in preselected
            ],
        }

    def _fields(self, data, formation):
        if not isinstance(data, dict):
            raise InterviewValidationError("Bootcamp invalide.")
        start, end = _date(data.get("start_date"), "date de début"), _date(data.get("end_date"), "date de fin")
        if end < start:
            raise InterviewValidationError("La date de fin doit être postérieure ou égale à la date de début.")
        coaches = data.get("coach_ids", [])
        available = self._coaches(formation)
        if not isinstance(coaches, list) or len(coaches) > 10 or any(coach not in available for coach in coaches):
            raise InterviewValidationError("Choisissez des coachs actifs rattachés à ce référentiel.")
        capacity = data.get("capacity")
        if capacity in ("", None):
            capacity = None
        elif type(capacity) is not int or not 1 <= capacity <= 5000:
            raise InterviewValidationError("La capacité doit être comprise entre 1 et 5 000.")
        return {
            "title": _text(data.get("title"), "L’intitulé", 150, required=True), "coach_ids": list(dict.fromkeys(coaches)),
            "start_date": start, "end_date": end, "location": _text(data.get("location"), "Le lieu", 200),
            "description": _text(data.get("description"), "La description", 3000), "capacity": capacity,
        }

    def create(self, formation, data, campaign_id=None):
        workspace, training, source = self._workspace(formation, campaign_id)
        if (workspace.preselection or {}).get("status") != "validated":
            raise InterviewValidationError("Validez d’abord la présélection des entretiens de ce référentiel.")
        fields = self._fields(data, training["code"])
        bootcamp = Bootcamp(formation=training["code"], candidature_campaign_id=str(source.id),
                            interview_campaign_id=str(workspace.id), **fields).save()
        return {"id": str(bootcamp.id)}

    def update(self, bootcamp_id, data):
        bootcamp = self._bootcamp(bootcamp_id)
        self._check_revision(bootcamp, data.get("revision") if isinstance(data, dict) else None)
        fields = self._fields(data, bootcamp.formation)
        if bootcamp.status != "draft":
            # Once invitations left, only the practical information may change; dates and coaches are fixed.
            fields = {key: fields[key] for key in ("location", "description")}
        if fields.get("capacity") and fields["capacity"] < BootcampParticipant.objects(bootcamp_id=bootcamp_id).count():
            raise InterviewValidationError("La capacité est inférieure au nombre de participants déjà affectés.")
        self._bump(bootcamp, **fields)
        return {"id": bootcamp_id}

    def delete(self, bootcamp_id):
        bootcamp = self._bootcamp(bootcamp_id)
        if bootcamp.status != "draft":
            raise InterviewConflictError("Un Bootcamp lancé ne peut plus être supprimé.")
        BootcampParticipant.objects(bootcamp_id=bootcamp_id).delete()
        bootcamp.delete()
        return {"deleted": bootcamp_id}

    def set_participants(self, bootcamp_id, data):
        """Replace the participant list of a draft Bootcamp with pre-selected candidates of its campaign."""
        bootcamp = self._bootcamp(bootcamp_id)
        if not isinstance(data, dict):
            raise InterviewValidationError("Participants invalides.")
        self._check_revision(bootcamp, data.get("revision"))
        if bootcamp.status != "draft":
            raise InterviewConflictError("Les participants d’un Bootcamp lancé ne peuvent plus être modifiés.")
        wanted = data.get("candidate_ids")
        workspace = self.referentials._find_workspace(bootcamp.formation, CandidatureCampaign.objects(id=bootcamp.candidature_campaign_id).first())
        allowed = set(self._preselected(workspace)) if workspace else set()
        if not isinstance(wanted, list) or any(candidate not in allowed for candidate in wanted):
            raise InterviewValidationError("Seuls les candidats présélectionnés peuvent participer au Bootcamp.")
        wanted = list(dict.fromkeys(wanted))
        if bootcamp.capacity and len(wanted) > bootcamp.capacity:
            raise InterviewValidationError(f"Ce Bootcamp accueille au maximum {bootcamp.capacity} participant(s).")
        current = set(BootcampParticipant.objects(bootcamp_id=bootcamp_id).distinct("candidate_id"))
        elsewhere = BootcampParticipant.objects(
            candidature_campaign_id=bootcamp.candidature_campaign_id, formation=bootcamp.formation,
            candidate_id__in=[candidate for candidate in wanted if candidate not in current],
        ).count()
        if elsewhere:
            raise InterviewConflictError(f"{elsewhere} candidat(s) sont déjà inscrits dans un autre Bootcamp de cette campagne.")
        self._bump(bootcamp)
        BootcampParticipant.objects(bootcamp_id=bootcamp_id, candidate_id__nin=wanted).delete()
        for candidate in wanted:
            if candidate in current:
                continue
            try:
                BootcampParticipant(bootcamp_id=bootcamp_id, candidature_campaign_id=bootcamp.candidature_campaign_id,
                                    formation=bootcamp.formation, candidate_id=candidate).save(force_insert=True)
            except NotUniqueError as error:
                raise InterviewConflictError("Un candidat vient d’être inscrit dans un autre Bootcamp. Actualisez.") from error
        return {"participants": len(wanted)}

    def launch(self, bootcamp_id, data, admin):
        """Check the Bootcamp is complete, mark it launched and queue the participants' invitations."""
        bootcamp = self._bootcamp(bootcamp_id)
        if not isinstance(data, dict) or data.get("confirmed") is not True:
            raise InterviewValidationError("Confirmez le lancement du Bootcamp.")
        self._check_revision(bootcamp, data.get("revision"))
        if bootcamp.status != "draft":
            raise InterviewConflictError("Ce Bootcamp est déjà lancé.")
        problems = []
        if not bootcamp.coach_ids:
            problems.append("désignez au moins un coach")
        if bootcamp.end_date < bootcamp.start_date:
            problems.append("corrigez les dates")
        if bootcamp.start_date < date.today():
            problems.append("la date de début est passée")
        count = BootcampParticipant.objects(bootcamp_id=bootcamp_id).count()
        if not count:
            problems.append("ajoutez des participants")
        if problems:
            raise InterviewValidationError("Lancement impossible : " + ", ".join(problems) + ".")
        outbox = BootcampInvitationOutbox()
        if not outbox.transport.is_configured:
            raise InterviewValidationError("Le service d’envoi des e-mails n’est pas configuré.")
        self._bump(bootcamp, status="launched", launched_at=datetime.utcnow(), launched_by=_actor(admin))
        return outbox.enqueue(bootcamp_id)

    def retry_invitations(self, bootcamp_id):
        bootcamp = self._bootcamp(bootcamp_id)
        outbox = BootcampInvitationOutbox()
        jobs = EmailJob.objects(kind=INVITATION_KIND, batch_key=str(bootcamp.id))
        outbox.requeue(jobs)
        return outbox.summarize(jobs)

    def reopen_results(self, bootcamp_id, data):
        bootcamp = self._bootcamp(bootcamp_id)
        self._check_revision(bootcamp, data.get("revision") if isinstance(data, dict) else None)
        if bootcamp.status != "submitted":
            raise InterviewConflictError("Les résultats de ce Bootcamp ne sont pas soumis.")
        self._bump(bootcamp, status="launched", submitted_at=None, submitted_by={})
        return {"id": bootcamp_id, "status": "launched"}

    # ----- coach ----------------------------------------------------------------------------------

    def _coach_bootcamp(self, bootcamp_id, coach):
        if not is_coach(coach):
            raise InterviewForbiddenError("Cet espace est réservé aux coachs.")
        bootcamp = self._bootcamp(bootcamp_id)
        if str(coach.id) not in bootcamp.coach_ids:
            raise InterviewForbiddenError("Ce Bootcamp n’est pas attribué à votre compte.")
        return bootcamp

    def coach_dashboard(self, coach):
        if not is_coach(coach):
            raise InterviewForbiddenError("Cet espace est réservé aux coachs.")
        bootcamps = list(Bootcamp.objects(coach_ids=str(coach.id), status__ne="draft").order_by("-start_date"))
        participants = list(BootcampParticipant.objects(bootcamp_id__in=[str(bootcamp.id) for bootcamp in bootcamps])) if bootcamps else []
        by_bootcamp = {}
        for participant in participants:
            by_bootcamp.setdefault(participant.bootcamp_id, []).append(participant)
        titles = {training["code"]: training["title"] for training in get_catalog()}
        coaches = self._coaches(include_inactive=True)
        totals = {decision: sum(participant.decision == decision for participant in participants) for decision in FINAL_DECISIONS}
        return {
            "referentials": sorted({titles.get(bootcamp.formation, bootcamp.formation) for bootcamp in bootcamps}),
            "bootcamps": [{**self._serialize(bootcamp, by_bootcamp.get(str(bootcamp.id), []), coaches=coaches),
                           "formation_title": titles.get(bootcamp.formation, bootcamp.formation)} for bootcamp in bootcamps],
            "totals": {"participants": len(participants), "to_evaluate": totals["pending"],
                       "evaluated": len(participants) - totals["pending"], "retained": totals["retained"],
                       "waiting_list": totals["waiting_list"], "rejected": totals["rejected"]},
        }

    def coach_bootcamp(self, bootcamp_id, coach):
        bootcamp = self._coach_bootcamp(bootcamp_id, coach)
        if bootcamp.status == "draft":
            raise InterviewForbiddenError("Ce Bootcamp n’est pas encore lancé.")
        participants = list(BootcampParticipant.objects(bootcamp_id=bootcamp_id))
        details = self._candidates({participant.candidate_id for participant in participants}, bootcamp.interview_campaign_id)
        rows = sorted((self._participant_row(participant, details) for participant in participants),
                      key=lambda row: ((row.get("last_name") or "").casefold(), (row.get("first_name") or "").casefold()))
        titles = {training["code"]: training["title"] for training in get_catalog()}
        return {**self._serialize(bootcamp, participants, coaches=self._coaches(include_inactive=True)),
                "formation_title": titles.get(bootcamp.formation, bootcamp.formation), "participants": rows}

    def coach_decide(self, bootcamp_id, candidate_id, data, coach):
        bootcamp = self._coach_bootcamp(bootcamp_id, coach)
        if bootcamp.status != "launched":
            raise InterviewConflictError("Les résultats ne peuvent être saisis que pendant un Bootcamp lancé et non soumis.")
        if not isinstance(data, dict):
            raise InterviewValidationError("Décision invalide.")
        decision = data.get("decision")
        if decision not in FINAL_DECISIONS:
            raise InterviewValidationError("Choisissez une décision.")
        comment = _text(data.get("comment"), "L’appréciation", 3000)
        updated = BootcampParticipant.objects(bootcamp_id=bootcamp_id, candidate_id=candidate_id).update_one(
            set__decision=decision, set__coach_comment=comment, set__decided_at=datetime.utcnow(), set__decided_by=_actor(coach),
        )
        if not updated:
            raise InterviewNotFoundError("Ce candidat ne participe pas à ce Bootcamp.")
        return {"candidate_id": candidate_id, "decision": decision, "coach_comment": comment}

    def coach_submit(self, bootcamp_id, data, coach):
        bootcamp = self._coach_bootcamp(bootcamp_id, coach)
        if not isinstance(data, dict) or data.get("confirmed") is not True:
            raise InterviewValidationError("Confirmez la soumission des résultats.")
        if bootcamp.status != "launched":
            raise InterviewConflictError("Les résultats de ce Bootcamp sont déjà soumis.")
        pending = BootcampParticipant.objects(bootcamp_id=bootcamp_id, decision="pending").count()
        if pending:
            raise InterviewValidationError(f"{pending} candidat(s) n’ont pas encore de décision.")
        Bootcamp.objects(id=bootcamp.id, status="launched").update_one(
            set__status="submitted", set__submitted_at=datetime.utcnow(), set__submitted_by=_actor(coach),
            inc__revision=1, set__updated_at=datetime.utcnow(),
        )
        return {"id": bootcamp_id, "status": "submitted"}


class BootcampInvitationOutbox(EmailOutbox):
    def enqueue(self, bootcamp_id):
        now = self.now()
        operations = []
        for participant in BootcampParticipant.objects(bootcamp_id=bootcamp_id).only("candidate_id"):
            key = sha256(f"bootcamp:{bootcamp_id}:{participant.candidate_id}".encode()).hexdigest()
            operations.append(UpdateOne({"dedup_key": key}, {"$setOnInsert": {
                "dedup_key": key, "batch_key": bootcamp_id, "kind": INVITATION_KIND, "candidate_id": participant.candidate_id,
                "status": "pending", "attempts": 0, "created_at": now, "next_attempt_at": now, "payload": {},
            }}, upsert=True))
        if operations:
            self._insert_jobs(EmailJob._get_collection(), operations)
        return self.summarize(EmailJob.objects(kind=INVITATION_KIND, batch_key=bootcamp_id))

    @staticmethod
    def prepare(job, _now):
        bootcamp = Bootcamp.objects(id=job.batch_key).first() if ObjectId.is_valid(job.batch_key) else None
        candidate = Candidature.objects(id=job.candidate_id, status__ne="rejected").only("first_name", "last_name", "email").first()
        if not bootcamp or not candidate or not BootcampParticipant.objects(bootcamp_id=job.batch_key, candidate_id=job.candidate_id).first():
            return None
        titles = {training["code"]: training["title"] for training in get_catalog()}
        dates = f"du {bootcamp.start_date.strftime('%d/%m/%Y')} au {bootcamp.end_date.strftime('%d/%m/%Y')}"
        parts = [
            f"<p>Bonjour {escape(_name(candidate))},</p>",
            f"<p>Félicitations : à l’issue des entretiens, vous êtes invité(e) au Bootcamp « {escape(bootcamp.title)} » "
            f"du référentiel {escape(titles.get(bootcamp.formation, bootcamp.formation))}, {dates}.</p>",
        ]
        if bootcamp.location:
            parts.append(f"<p>Lieu ou modalité : {escape(bootcamp.location)}</p>")
        if bootcamp.description:
            parts.append(f"<p>{escape(bootcamp.description)}</p>")
        parts.append("<p>Votre présence est indispensable. En cas d’empêchement, prévenez-nous au plus vite en répondant à ce message.</p>"
                     "<p>Orange Digital Center Sénégal</p>")
        return [candidate.email], f"Convocation au Bootcamp {bootcamp.title} – Orange Digital Center", "".join(parts)

    @staticmethod
    def on_accepted(_job, _now):
        pass
