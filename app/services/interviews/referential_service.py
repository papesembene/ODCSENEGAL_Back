"""Direct interview setup and dispatch for a referential."""

from datetime import datetime, timedelta
from hashlib import sha256
from html import escape
from random import Random, SystemRandom
import re
import secrets
from urllib.parse import urlsplit, urlunsplit

from bson import ObjectId
from mongoengine import NotUniqueError
from pymongo import UpdateOne

from app.models.candidature import Candidature
from app.models.candidature_campaign import CandidatureCampaign
from app.models.email_job import EmailJob
from app.models.interview import InterviewCampaign, InterviewEvaluation, InterviewSlot
from app.models.user import User
from app.repositories.candidature_filters import candidate_filter
from app.services.email_outbox import EmailOutbox
from app.services.interviews.evaluation_service import InterviewEvaluationService
from app.services.interviews.exceptions import InterviewConflictError, InterviewValidationError
from app.services.interviews.member_roles import role_query
from app.services.interviews.query_service import InterviewQueryService
from app.services.interviews.scheduling import LEGACY_MINUTES, normalize_schedule, plan_times, validator_intervals
from app.services.trainings.age_rules import parse_age_rule
from app.services.trainings.catalog import get_catalog, require_training


INVITATION_KIND = "interview_invitation"
VALIDATOR_SCHEDULE_KIND = "interview_validator_schedule"
LEGACY_CAMPAIGN = "historique"


def _teams_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(char.isspace() or ord(char) < 32 for char in value):
        raise InterviewValidationError("Lien Teams invalide.")
    try:
        parts = urlsplit(value)
        host = parts.netloc.lower()
    except ValueError as error:
        raise InterviewValidationError("Lien Teams invalide.") from error
    if parts.scheme != "https" or host not in {"teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft"} or parts.path in {"", "/"}:
        raise InterviewValidationError("Utilisez un lien de réunion Microsoft Teams en HTTPS.")
    return urlunsplit(("https", host, parts.path.rstrip("/"), parts.query, ""))


class ReferentialInterviews:
    @staticmethod
    def _sources(code, now):
        return list(CandidatureCampaign.objects(
            formation__in=[code, "all"], status__in=["published", "archived"], start_at__lte=now,
        ).order_by("-start_at", "-id"))

    @staticmethod
    def _default_source(sources, now):
        published = [source for source in sources if source.status == "published"]
        opened = next((source for source in published if source.end_at >= now), None)
        return opened or next(iter(sources), None)

    def _workspace(self, formation, *, create=False, campaign_id=None):
        # An empty identifier (page opened without ?campaign_id=) means the referential's default campaign.
        campaign_id = campaign_id or None
        training = require_training(formation)
        code = training["code"]
        now = datetime.utcnow()
        sources = self._sources(code, now)
        source = None
        if campaign_id == LEGACY_CAMPAIGN:
            workspace = InterviewCampaign.objects(referential_key=code).first()
            if not workspace:
                raise InterviewValidationError("Historique introuvable pour ce référentiel.")
        elif campaign_id is not None:
            source = next((item for item in sources if str(item.id) == campaign_id), None)
            if not source:
                raise InterviewValidationError("Campagne de candidature indisponible pour ce référentiel.")
        else:
            source = self._default_source(sources, now)

        if campaign_id != LEGACY_CAMPAIGN:
            workspace = self._find_workspace(code, source)
        if workspace or not create:
            return workspace, training, source
        if not source:
            raise InterviewValidationError("Ouvrez d’abord une campagne de candidature pour ce référentiel.")
        key = f"{code}:{source.id}"
        try:
            return InterviewCampaign(
                referential_key=key, candidature_campaign_id=str(source.id),
                formation=code, name=f"{training['title']} · {source.title}", status="active",
                distribution={"revision": 0, "validators": {}},
            ).save(force_insert=True), training, source
        except NotUniqueError:
            return InterviewCampaign.objects(referential_key=key).get(), training, source

    @staticmethod
    def _find_workspace(code, source):
        legacy = InterviewCampaign.objects(referential_key=code).first()
        if not source:
            return legacy
        workspace = InterviewCampaign.objects(referential_key=f"{code}:{source.id}").first()
        if workspace:
            return workspace
        if legacy and ReferentialInterviews._legacy_source_id(legacy) == str(source.id):
            return legacy
        return None

    @staticmethod
    def _legacy_source_id(workspace):
        ids = {candidate for item in workspace.distribution["validators"].values() for candidate in item["candidates"]}
        if not ids:
            return None
        candidates = list(Candidature.objects(id__in=ids).only("candidature_campaign_id"))
        sources = {candidate.candidature_campaign_id for candidate in candidates}
        if len(candidates) == len(ids) and len(sources) == 1:
            return sources.pop()
        return None

    @staticmethod
    def _campaign_label(source, now):
        return {"id": str(source.id), "title": source.title, "promotion": source.promotion or "",
                "is_open": source.lifecycle_status(now) == "open"}

    @staticmethod
    def _validators(formation=None, *, include_inactive=False):
        users = User.objects(
            is_admin=True, admin_type__in=["competences", "super_admin"],
            profile_data__admin_scope="interview_member", __raw__=role_query("validator"),
        )
        if not include_inactive:
            users = users.filter(is_active=True)
        if formation:
            users = users.filter(profile_data__interview_formations=formation)
        users = users.only("id", "first_name", "last_name", "email").order_by("first_name", "last_name")
        return {str(user.id): {"id": str(user.id), "name": f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email, "email": user.email} for user in users}

    @staticmethod
    def _eligible(training, campaign_id=None, *, historical_ids=None):
        query = Candidature.objects(__raw__=candidate_filter({"desired_training": training["code"]}))
        if campaign_id:
            query = query.filter(candidature_campaign_id=campaign_id)
        elif historical_ids is not None:
            query = query.filter(id__in=historical_ids)
        else:
            return []
        query = query.only(
            "status", "date_of_birth", "created_at", "first_name", "last_name", "email", "phone", "gender", "desired_training",
        ).order_by("created_at", "id")
        rule = parse_age_rule(training.get("level"))
        return [candidate for candidate in query if InterviewEvaluationService._is_direct_candidate_eligible(candidate, rule)]

    def overview_campaigns(self):
        """Candidature campaigns that can drive the interviews overview, most recent first."""
        now = datetime.utcnow()
        titles = {training["code"]: training["title"] for training in get_catalog()}
        return [{
            **self._campaign_label(source, now),
            "formation": source.formation,
            "scope": "Tous les référentiels" if source.formation == "all" else titles.get(source.formation, source.formation),
        } for source in CandidatureCampaign.objects(
            status__in=["published", "archived"], start_at__lte=now,
        ).order_by("-start_at", "-id")]

    def overview(self, campaign_id=None):
        """One row per referential; by default each uses its current campaign, or the chosen campaign when given."""
        workspaces = {item.referential_key: item for item in InterviewCampaign.objects(referential_key__ne=None)}
        candidates = []
        now = datetime.utcnow()
        chosen = None
        if campaign_id:
            chosen = CandidatureCampaign.objects(
                id=campaign_id, status__in=["published", "archived"], start_at__lte=now,
            ).first() if ObjectId.is_valid(campaign_id) else None
            if not chosen:
                raise InterviewValidationError("Campagne de candidature introuvable.")
        for training in get_catalog():
            code = training["code"]
            if chosen and chosen.formation not in (code, "all"):
                continue
            source = chosen or self._default_source(self._sources(code, now), now)
            legacy = workspaces.get(code)
            workspace = workspaces.get(f"{code}:{source.id}") if source else legacy
            if source and not workspace and legacy and self._legacy_source_id(legacy) == str(source.id):
                workspace = legacy
            if training["status"] == "archived" or (training["status"] != "published" and not workspace):
                continue
            validators = workspace.distribution.get("validators", {}) if workspace else {}
            historical_ids = [candidate for item in validators.values() for candidate in item["candidates"]]
            eligible = len(self._eligible(training, str(source.id) if source else None, historical_ids=historical_ids))
            evaluations = InterviewEvaluation.objects(campaign_id=str(workspace.id)) if workspace else None
            completed = evaluations.filter(interview_progress_status="passe").count() if workspace else 0
            absent = evaluations.filter(interview_progress_status="absent").count() if workspace else 0
            candidates.append({
                "formation": code, "title": training["title"], "eligible": eligible,
                "candidature_campaign": self._campaign_label(source, now) if source else None,
                "validators": len(validators), "assigned": sum(len(item["candidates"]) for item in validators.values()),
                "completed": completed, "remaining": max(0, eligible - completed - absent),
            })
        return candidates

    @staticmethod
    def _save(workspace, revision, config):
        if type(revision) is not int or revision != workspace.distribution.get("revision"):
            raise InterviewConflictError("Le référentiel a changé. Actualisez avant de recommencer.")
        config["revision"] = revision + 1
        if not InterviewCampaign.objects(id=workspace.id, distribution__revision=revision).update_one(
            set__distribution=config, set__updated_at=datetime.utcnow(),
        ):
            raise InterviewConflictError("Le référentiel a changé. Actualisez avant de recommencer.")

    def prepare_questions(self, formation, data):
        self._workspace(formation, create=True, campaign_id=data.get("campaign_id"))
        return {"prepared": True}

    def settings(self, formation, data):
        if not isinstance(data, dict):
            raise InterviewValidationError("Paramètres invalides.")
        selected = data.get("validators")
        workspace, training, _ = self._workspace(formation, create=True, campaign_id=data.get("campaign_id"))
        available = self._validators(training["code"])
        if not isinstance(selected, list) or len(selected) > 200 or any(not isinstance(value, str) or value not in available for value in selected):
            raise InterviewValidationError("Sélectionnez des validateurs actifs rattachés à ce référentiel.")
        config = workspace.distribution
        previous = config["validators"]
        if selected and not config.get("links") and not any(item.get("teams_url") for item in previous.values()):
            raise InterviewValidationError("Importez d’abord les liens Teams.")
        if any(item["candidates"] and user_id not in selected for user_id, item in previous.items()):
            raise InterviewConflictError("Un validateur qui a déjà des candidats ne peut pas être retiré.")
        released = [item["teams_url"] for user_id, item in previous.items() if user_id not in selected and item.get("teams_url")]
        config = {**config, "links": [*config.get("links", []), *released],
                  "validators": {user_id: previous.get(user_id, {"slot_id": str(ObjectId()), "candidates": []}) for user_id in dict.fromkeys(selected)}}
        self._save(workspace, data.get("revision"), config)

    def import_links(self, formation, data):
        links = data.get("links") if isinstance(data, dict) else None
        if not isinstance(links, list) or not 1 <= len(links) <= 200:
            raise InterviewValidationError("Importez entre 1 et 200 liens Teams.")
        urls = [_teams_url(link.strip()) if isinstance(link, str) else _teams_url(link) for link in links]
        if len(set(urls)) != len(urls):
            raise InterviewValidationError("Le fichier contient des liens Teams en double.")
        workspace, _, _ = self._workspace(formation, create=True, campaign_id=data.get("campaign_id"))
        config = workspace.distribution
        known_links = set(config.get("links", [])) | {item.get("teams_url") for item in config["validators"].values()}
        additional_links = [url for url in urls if url not in known_links]
        self._save(workspace, data.get("revision"), {**config, "links": [*config.get("links", []), *additional_links]})
        return {"imported": len(additional_links)}

    def assign_links(self, formation, data):
        workspace, training, _ = self._workspace(formation, campaign_id=data.get("campaign_id"))
        if not workspace:
            raise InterviewValidationError("Importez d’abord les liens Teams.")
        config = workspace.distribution
        urls = list(config.get("links", []))
        available = self._validators(training["code"])
        pending = [item for user_id, item in config["validators"].items() if user_id in available and not item.get("teams_url")]
        if not urls or not pending:
            raise InterviewValidationError("Ajoutez des liens Teams et sélectionnez les validateurs sans lien.")
        random = SystemRandom()
        random.shuffle(urls)
        random.shuffle(pending)
        for item, url in zip(pending, urls):
            item["teams_url"] = url
        assigned = min(len(pending), len(urls))
        config["links"] = urls[assigned:]
        self._save(workspace, data.get("revision"), config)
        return {"assigned": assigned}

    @staticmethod
    def _busy(user_id):
        """Intervals already booked for this validator, across every referential."""
        intervals = []
        for workspace in InterviewCampaign.objects(__raw__={f"distribution.validators.{user_id}": {"$exists": True}}).only("distribution"):
            intervals.extend(validator_intervals(workspace.distribution, user_id))
        return intervals

    def dispatch(self, formation, data):
        """Preview (preview=true) or confirm (same seed) a random, balanced dispatch with individual times."""
        if not isinstance(data, dict):
            raise InterviewValidationError("Répartition invalide.")
        workspace, training, source = self._workspace(formation, campaign_id=data.get("campaign_id"))
        if not workspace or not source:
            raise InterviewValidationError("Configurez les validateurs et les liens Teams.")
        config = workspace.distribution
        if data.get("revision") != config.get("revision"):
            raise InterviewConflictError("Le référentiel a changé. Actualisez avant de recommencer.")
        validators = config["validators"]
        active = self._validators(training["code"])
        if not validators or any(user_id not in active or not item.get("teams_url") for user_id, item in validators.items()):
            raise InterviewValidationError("Chaque validateur doit être actif et disposer d’un lien Teams.")
        capacity = data.get("per_validator")
        if type(capacity) is not int or not 1 <= capacity <= 5000:
            raise InterviewValidationError("Indiquez entre 1 et 5 000 candidats par validateur.")
        if any(len(item["candidates"]) > capacity for item in validators.values()):
            raise InterviewValidationError("La limite est inférieure à un effectif déjà affecté.")
        schedule = normalize_schedule(data.get("schedule"))
        preview = data.get("preview") is True
        seed = data.get("seed")
        if seed is None and not preview:
            raise InterviewValidationError("Prévisualisez la répartition avant de la confirmer.")
        if seed is None:
            seed = secrets.token_hex(8)
        elif not isinstance(seed, str) or not re.fullmatch(r"[0-9a-f]{16}", seed):
            raise InterviewValidationError("Aperçu de répartition invalide. Relancez la prévisualisation.")

        candidates = self._eligible(training, str(source.id))
        already = {candidate for item in validators.values() for candidate in item["candidates"]}
        pending = [str(candidate.id) for candidate in candidates if str(candidate.id) not in already]
        Random(seed).shuffle(pending)
        counts = {user_id: len(item["candidates"]) for user_id, item in validators.items()}
        plan = {user_id: [] for user_id in validators}
        for candidate_id in pending:
            user_id = min(counts, key=counts.get)
            if counts[user_id] >= capacity:
                break
            plan[user_id].append(candidate_id)
            counts[user_id] += 1
        now = datetime.utcnow()
        times = {user_id: plan_times(schedule, self._busy(user_id), len(ids), now) for user_id, ids in plan.items()}
        planned = sum(len(ids) for ids in plan.values())
        if sum(counts.values()) > 100000:
            raise InterviewValidationError("Le référentiel dépasse la capacité de stockage des affectations.")

        names = {}
        if preview and planned:
            ids = [candidate_id for values in plan.values() for candidate_id in values]
            names = {str(candidate.id): f"{candidate.first_name or ''} {candidate.last_name or ''}".strip() or candidate.email
                     for candidate in Candidature.objects(id__in=ids).only("first_name", "last_name", "email")}
        known = self._validators(include_inactive=True)
        result = {
            "seed": seed, "schedule": schedule, "new_assignments": planned, "unassigned": len(pending) - planned,
            "validators": [{
                "id": user_id, "name": known.get(user_id, {}).get("name", "Compte indisponible"),
                "existing": len(validators[user_id]["candidates"]), "new": len(ids),
                "first": times[user_id][0].isoformat(timespec="minutes") if ids else None,
                "last": times[user_id][-1].isoformat(timespec="minutes") if ids else None,
                **({"candidates": [{"name": names.get(candidate_id, ""), "at": at.isoformat(timespec="minutes")}
                                   for candidate_id, at in zip(ids, times[user_id])]} if preview else {}),
            } for user_id, ids in plan.items()],
        }
        if preview:
            return {**result, "preview": True}

        for user_id, ids in plan.items():
            item = validators[user_id]
            slots = item.setdefault("slots", {})
            for candidate_id, at in zip(ids, times[user_id]):
                item["candidates"].append(candidate_id)
                slots[candidate_id] = {"at": at.isoformat(timespec="minutes"), "minutes": schedule["duration"]}
        first_times = [values[0] for values in times.values() if values]
        if first_times and not config.get("starts_at"):
            config["starts_at"] = min(first_times).isoformat(timespec="minutes")
        config["schedule"] = schedule
        config["per_validator"] = capacity
        self._save(workspace, data.get("revision"), config)
        self._project(workspace, config)
        return {**result, "preview": False}

    @staticmethod
    def candidate_time(config, item, candidate_id):
        """Start time and duration of a candidate's interview, including legacy shared start times."""
        slot = (item.get("slots") or {}).get(candidate_id)
        if slot:
            return slot["at"], slot["minutes"]
        return config.get("starts_at"), LEGACY_MINUTES if config.get("starts_at") else None

    def set_link(self, formation, data):
        """Replace one validator's Teams link by hand, as long as no invitation carrying the old link has left."""
        if not isinstance(data, dict):
            raise InterviewValidationError("Lien Teams invalide.")
        workspace, _, _ = self._workspace(formation, campaign_id=data.get("campaign_id"))
        if not workspace:
            raise InterviewValidationError("Configurez d’abord les validateurs du référentiel.")
        config = workspace.distribution
        if data.get("revision") != config.get("revision"):
            raise InterviewConflictError("Le référentiel a changé. Actualisez avant de recommencer.")
        user_id = data.get("validator_id")
        item = config["validators"].get(user_id) if isinstance(user_id, str) else None
        if item is None:
            raise InterviewValidationError("Ce validateur ne fait pas partie de la campagne.")
        url = _teams_url(data.get("teams_url"))
        if any(other_id != user_id and other.get("teams_url") == url for other_id, other in config["validators"].items()):
            raise InterviewValidationError("Ce lien est déjà attribué à un autre validateur.")
        if item["candidates"] and EmailJob.objects(
            kind=INVITATION_KIND, batch_key=str(workspace.id), candidate_id__in=item["candidates"],
        ).first():
            raise InterviewConflictError("Des convocations avec l’ancien lien sont déjà parties : le lien de ce validateur ne peut plus être modifié.")
        item["teams_url"] = url
        config["links"] = [link for link in config.get("links", []) if link != url]
        self._save(workspace, data.get("revision"), config)
        InterviewSlot._get_collection().update_one({"_id": ObjectId(item["slot_id"])}, {"$set": {"teams_url": url}})
        return {"validator_id": user_id, "teams_url": url}

    def notify_validators(self, formation, data):
        """Queue one planning e-mail per validator; an unchanged planning is not sent twice."""
        if not isinstance(data, dict) or data.get("confirmed") is not True:
            raise InterviewValidationError("Confirmez l’envoi des plannings.")
        workspace, training, _ = self._workspace(formation, campaign_id=data.get("campaign_id"))
        if not workspace:
            raise InterviewValidationError("Aucune répartition pour ce référentiel.")
        outbox = ValidatorScheduleOutbox()
        if not outbox.transport.is_configured:
            raise InterviewValidationError("Le service d’envoi des e-mails n’est pas configuré.")
        return outbox.enqueue(workspace, training["title"])

    def reassign(self, formation, data):
        """Manually move one candidate to a validator (or back to unassigned) before the invitation leaves."""
        if not isinstance(data, dict):
            raise InterviewValidationError("Affectation invalide.")
        workspace, training, source = self._workspace(formation, campaign_id=data.get("campaign_id"))
        if not workspace or not source:
            raise InterviewValidationError("Configurez d’abord les validateurs du référentiel.")
        config = workspace.distribution
        if data.get("revision") != config.get("revision"):
            raise InterviewConflictError("Le référentiel a changé. Actualisez avant de recommencer.")
        candidate_id = data.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in {str(item.id) for item in self._eligible(training, str(source.id))}:
            raise InterviewValidationError("Ce candidat n’est pas éligible dans cette campagne.")
        workspace_id = str(workspace.id)
        if EmailJob.objects(kind=INVITATION_KIND, batch_key=workspace_id, candidate_id=candidate_id).first():
            raise InterviewConflictError("La convocation de ce candidat est déjà envoyée ou en cours d’envoi : il ne peut plus être déplacé.")
        evaluation = InterviewEvaluation.objects(campaign_id=workspace_id, candidature_id=candidate_id).first()
        if evaluation and evaluation.questionnaire.get("status"):
            raise InterviewConflictError("L’entretien de ce candidat a déjà commencé.")

        validators = config["validators"]
        target_id = data.get("validator_id")
        previous_id = next((user_id for user_id, item in validators.items() if candidate_id in item["candidates"]), None)
        if target_id is not None:
            active = self._validators(training["code"])
            target = validators.get(target_id) if isinstance(target_id, str) else None
            if not target or target_id not in active or not target.get("teams_url"):
                raise InterviewValidationError("Choisissez un validateur actif de la campagne, avec un lien Teams.")
            schedule = config.get("schedule")
            duration = schedule["duration"] if schedule else data.get("duration")
            if type(duration) is not int or not 5 <= duration <= 180:
                raise InterviewValidationError("Indiquez une durée d’entretien entre 5 et 180 minutes.")
            busy = [
                (start, stop) for start, stop in self._busy(target_id)
                if not (target_id == previous_id and (target.get("slots") or {}).get(candidate_id)
                        and start == datetime.fromisoformat(target["slots"][candidate_id]["at"]))
            ]
            now = datetime.utcnow()
            requested = data.get("at")
            if requested:
                try:
                    at = datetime.strptime(requested, "%Y-%m-%dT%H:%M")
                except (TypeError, ValueError) as error:
                    raise InterviewValidationError("Horaire invalide.") from error
                if at < now:
                    raise InterviewValidationError("Choisissez un horaire à venir.")
                stop = at + timedelta(minutes=duration)
                if any(start < stop and at < end for start, end in busy):
                    raise InterviewConflictError("Ce validateur a déjà un entretien sur ce créneau.")
            elif schedule:
                at = plan_times(schedule, busy, 1, now)[0]
            else:
                raise InterviewValidationError("Indiquez l’horaire de l’entretien.")

        if previous_id:
            previous = validators[previous_id]
            previous["candidates"].remove(candidate_id)
            (previous.get("slots") or {}).pop(candidate_id, None)
        if target_id is not None:
            target["candidates"].append(candidate_id)
            target.setdefault("slots", {})[candidate_id] = {"at": at.isoformat(timespec="minutes"), "minutes": duration}
            if not config.get("starts_at"):
                config["starts_at"] = at.isoformat(timespec="minutes")
        self._save(workspace, data.get("revision"), config)

        if evaluation and target_id is None:
            evaluation.delete()
        elif evaluation:
            InterviewEvaluation.objects(id=evaluation.id).update_one(
                set__slot_id=target["slot_id"], set__scheduled_at=at, set__scheduled_minutes=duration,
                set__updated_at=datetime.utcnow(),
            )
        self._project(workspace, config)
        return {
            "candidate_id": candidate_id, "validator_id": target_id,
            "at": at.isoformat(timespec="minutes") if target_id is not None else None,
        }

    @classmethod
    def _project(cls, workspace, config):
        now = datetime.utcnow()
        workspace_id = str(workspace.id)
        existing = set(InterviewEvaluation.objects(campaign_id=workspace_id).distinct("candidature_id"))
        for user_id, item in config["validators"].items():
            if not item["candidates"]:
                continue
            intervals = validator_intervals(config, user_id)
            if not intervals:
                continue
            slot_id = item["slot_id"]
            InterviewSlot._get_collection().update_one({"_id": ObjectId(slot_id)}, {
                "$setOnInsert": {"campaign_id": workspace_id, "formation": workspace.formation,
                                 "label": "Entretiens Teams", "status": "scheduled",
                                 "teams_url": item["teams_url"], "assigned_validator_ids": [user_id], "created_at": now},
                "$min": {"start_at": min(start for start, _ in intervals)},
                "$max": {"end_at": max(stop for _, stop in intervals)},
            }, upsert=True)
            missing = [candidate_id for candidate_id in item["candidates"] if candidate_id not in existing]
            for offset in range(0, len(missing), 500):
                ids = missing[offset:offset + 500]
                candidates = Candidature.objects(id__in=ids)
                operations = []
                for candidate in candidates:
                    at, minutes = cls.candidate_time(config, item, str(candidate.id))
                    operations.append(UpdateOne({"campaign_id": workspace_id, "candidature_id": str(candidate.id)}, {"$setOnInsert": {
                        "slot_id": slot_id, "candidate_snapshot": InterviewQueryService.build_candidate_snapshot(candidate),
                        "interview_progress_status": "planifie", "final_status": "en_attente", "is_complete": False,
                        "is_locked": False, "created_at": now, "updated_at": now,
                        "scheduled_at": datetime.fromisoformat(at) if at else None, "scheduled_minutes": minutes,
                    }}, upsert=True))
                if operations:
                    EmailOutbox._insert_jobs(InterviewEvaluation._get_collection(), operations)

    def get(self, formation, search="", page=1, *, group=None, groups_only=False, campaign_id=None):
        workspace, training, source = self._workspace(formation, campaign_id=campaign_id)
        config = workspace.distribution if workspace else {"revision": 0, "validators": {}}
        available = self._validators(training["code"])
        validators = config["validators"]
        known_validators = self._validators(include_inactive=True) if validators.keys() - available.keys() else available
        assigned_to = {candidate: user_id for user_id, item in validators.items() for candidate in item["candidates"]}
        candidates = self._eligible(training, str(source.id) if source else None, historical_ids=list(assigned_to))
        eligible_count = len(candidates)
        eligible_ids = {str(candidate.id) for candidate in candidates}
        search_term = search.casefold()
        if search_term:
            candidates = [candidate for candidate in candidates if search_term in
                          f"{candidate.first_name} {candidate.last_name} {candidate.email} {candidate.phone}".casefold()]

        unassigned = "unassigned"
        candidate_groups = []
        if group is None:
            group_counts = dict.fromkeys(validators, 0)
            for candidate in candidates:
                key = assigned_to.get(str(candidate.id), unassigned)
                group_counts[key] = group_counts.get(key, 0) + 1
            for key, count in group_counts.items():
                if search_term and not count:
                    continue
                name = "Sans validateur" if key == unassigned else known_validators.get(key, {}).get("name", "Compte indisponible")
                candidate_groups.append({"id": key, "name": name, "count": count})
        else:
            candidates = [candidate for candidate in candidates if assigned_to.get(str(candidate.id), unassigned) == group]

        page_size = 25
        total = len(candidates)
        if group is not None:
            page = min(page, max(1, (total + page_size - 1) // page_size))
        candidates = [] if groups_only else candidates[(page - 1) * page_size:page * page_size]
        ids = [str(candidate.id) for candidate in candidates]
        details = {str(candidate.id): InterviewQueryService.candidate_details(candidate)
                   for candidate in Candidature.objects(id__in=ids).only(
                       "education_level", "speciality", "current_structure", "region_of_residence",
                       "training_site_name", "computer_skills", "available_for_10_months",
                   )} if ids else {}
        workspace_id = str(workspace.id) if workspace else ""
        evaluations = {item.candidature_id: item for item in InterviewEvaluation.objects(campaign_id=workspace_id, candidature_id__in=ids).only(
            "id", "candidature_id", "questionnaire", "interview_progress_status", "final_status",
        )} if workspace and ids else {}
        jobs = EmailJob.objects(kind=INVITATION_KIND, batch_key=workspace_id) if workspace else None
        emails = {job.candidate_id: job.status for job in jobs.filter(candidate_id__in=ids).only("candidate_id", "status")} if workspace and ids else {}
        records = []
        for candidate in candidates:
            candidate_id = str(candidate.id)
            validator_id = assigned_to.get(candidate_id)
            item = evaluations.get(candidate_id)
            records.append({
                "id": candidate_id, "candidate_snapshot": {
                    **InterviewQueryService.build_candidate_snapshot(candidate), **details.get(candidate_id, {}),
                },
                "evaluation_id": str(item.id) if item else None, "final_status": item.final_status if item else None,
                "score": (item.questionnaire.get("scores") or {}).get("global") if item else None,
                "status": self._record_status(item, validator_id, emails.get(candidate_id)),
                "scheduled_at": self.candidate_time(config, validators[validator_id], candidate_id)[0] if validator_id else None,
                "validator": known_validators.get(validator_id, {}).get("name", "Compte indisponible") if validator_id else None,
                "email_status": emails.get(candidate_id),
            })
        candidate_page = {"candidates": records, "total": total, "page": page}
        if group is not None:
            return {**candidate_page, "page_size": page_size}

        now = datetime.utcnow()
        campaign_options = [self._campaign_label(item, now) for item in self._sources(training["code"], now)]
        selected_campaign = self._campaign_label(source, now) if source else None
        legacy = workspace if workspace and not source else InterviewCampaign.objects(referential_key=training["code"]).first()
        legacy_source = self._legacy_source_id(legacy) if legacy else None
        if legacy and (campaign_id == LEGACY_CAMPAIGN or not any(item["id"] == legacy_source for item in campaign_options)):
            historical = {"id": LEGACY_CAMPAIGN, "title": "Historique des entretiens", "promotion": "", "is_open": False}
            campaign_options.append(historical)
            if not source and workspace:
                selected_campaign = historical
        return {
            "workspace_id": workspace_id, "revision": config["revision"], "eligible": eligible_count,
            "available_links": len(config.get("links", [])),
            "assigned": len(assigned_to), "eligible_assigned": len(eligible_ids & assigned_to.keys()),
            "remaining_to_notify": len((eligible_ids & assigned_to.keys()) - set(jobs.distinct("candidate_id"))) if workspace else 0,
            "starts_at": config.get("starts_at"), "per_validator": config.get("per_validator"),
            "schedule": config.get("schedule"),
            "available_validators": list(available.values()),
            "notifications": InterviewInvitationOutbox.summarize(jobs) if workspace else {},
            "validator_notifications": ValidatorScheduleOutbox.summarize(
                EmailJob.objects(kind=VALIDATOR_SCHEDULE_KIND, batch_key=workspace_id),
            ) if workspace else {},
            "validators": [{**known_validators.get(user_id, {"id": user_id, "name": "Compte indisponible"}),
                            "active": user_id in available, "teams_url": item.get("teams_url"), "assigned": len(item["candidates"])}
                           for user_id, item in validators.items()],
            "candidate_groups": candidate_groups, "candidature_campaign": selected_campaign,
            "candidature_campaigns": campaign_options, **candidate_page,
        }

    @staticmethod
    def _record_status(evaluation, validator_id, email_status):
        status = evaluation.questionnaire.get("status") if evaluation else None
        if status:
            return status
        if not validator_id:
            return "unassigned"
        return "convened" if email_status == "sent" else "assigned"

    def notify(self, formation, data):
        if not isinstance(data, dict):
            raise InterviewValidationError("Confirmez l’envoi des convocations.")
        workspace, training, _ = self._workspace(formation, campaign_id=data.get("campaign_id"))
        if not workspace or data.get("confirmed") is not True:
            raise InterviewValidationError("Confirmez l’envoi des convocations.")
        if data.get("revision") != workspace.distribution["revision"]:
            raise InterviewConflictError("Les affectations ont changé. Actualisez avant d’envoyer.")
        outbox = InterviewInvitationOutbox()
        if not outbox.transport.is_configured:
            raise InterviewValidationError("Le service d’envoi des e-mails n’est pas configuré.")
        config = workspace.distribution
        self._project(workspace, config)
        return outbox.enqueue(workspace, training["title"], retry=data.get("retry") is True)


class InterviewInvitationOutbox(EmailOutbox):
    def enqueue(self, workspace, title, *, retry=False):
        config = workspace.distribution
        workspace_id = str(workspace.id)
        jobs = EmailJob.objects(kind=INVITATION_KIND, batch_key=workspace_id)
        if retry:
            self.requeue(jobs)
            return self.summarize(jobs)
        now = self.now()
        existing = set(jobs.distinct("candidate_id"))
        for item in config["validators"].values():
            pending = [candidate_id for candidate_id in item["candidates"] if candidate_id not in existing]
            for offset in range(0, len(pending), 500):
                candidates = Candidature.objects(id__in=pending[offset:offset + 500], status__ne="rejected").only("id", "email")
                operations = []
                for candidate in candidates:
                    at, minutes = ReferentialInterviews.candidate_time(config, item, str(candidate.id))
                    if not at:
                        continue
                    key = sha256(f"interview:{workspace_id}:{candidate.id}".encode()).hexdigest()
                    operations.append(UpdateOne({"dedup_key": key}, {"$setOnInsert": {
                        "dedup_key": key, "batch_key": workspace_id, "kind": INVITATION_KIND,
                        "candidate_id": str(candidate.id), "status": "pending", "attempts": 0,
                        "created_at": now, "next_attempt_at": now,
                        "payload": {"email": candidate.email, "teams_url": item["teams_url"],
                                    "starts_at": at, "minutes": minutes, "formation": title},
                    }}, upsert=True))
                if operations:
                    self._insert_jobs(EmailJob._get_collection(), operations)
        return self.summarize(jobs)

    @staticmethod
    def prepare(job, _now):
        candidate = Candidature.objects(id=job.candidate_id, status__ne="rejected").only("first_name", "last_name", "email").first()
        if not candidate or candidate.email != job.payload.get("email"):
            return None
        name = escape(f"{candidate.first_name} {candidate.last_name}")
        team = escape(_teams_url(job.payload["teams_url"]), quote=True)
        date = datetime.fromisoformat(job.payload["starts_at"]).strftime("%d/%m/%Y à %Hh%M")
        formation = escape(job.payload["formation"])
        minutes = int(job.payload.get("minutes") or LEGACY_MINUTES)
        html = (f"<p>Bonjour {name},</p><p>Votre entretien pour le référentiel {formation} est prévu le {date}, heure de Dakar.</p>"
                f"<p>Durée prévue : {minutes} minutes.</p>"
                f'<p><a href="{team}">Rejoindre la réunion Microsoft Teams</a></p>'
                "<p>Connectez-vous quelques minutes avant l’heure indiquée et patientez dans la salle d’attente : votre validateur vous admettra à votre tour. "
                "Prévoyez une connexion stable, un micro et une pièce calme.</p>"
                "<p>Orange Digital Center Sénégal</p>")
        return [candidate.email], "Convocation à un entretien – Orange Digital Center", html

    @staticmethod
    def on_accepted(_job, _now):
        pass


class ValidatorScheduleOutbox(EmailOutbox):
    """Planning e-mail sent to each validator: Teams link and the list of candidates with their times."""

    @staticmethod
    def _planning(config, item):
        rows = [(ReferentialInterviews.candidate_time(config, item, candidate_id)[0] or "", candidate_id)
                for candidate_id in item["candidates"]]
        return sorted(rows)

    def enqueue(self, workspace, title):
        config = workspace.distribution
        workspace_id = str(workspace.id)
        users = {str(user.id): user for user in User.objects(id__in=list(config["validators"]), is_active=True).only("email")}
        now = self.now()
        operations, unchanged = [], 0
        for user_id, item in config["validators"].items():
            user = users.get(user_id)
            if not user or not item["candidates"] or not item.get("teams_url"):
                continue
            signature = sha256(repr((item["teams_url"], self._planning(config, item))).encode()).hexdigest()
            key = sha256(f"validator-schedule:{workspace_id}:{user_id}:{signature}".encode()).hexdigest()
            if EmailJob.objects(dedup_key=key).first():
                unchanged += 1
                continue
            operations.append(UpdateOne({"dedup_key": key}, {"$setOnInsert": {
                "dedup_key": key, "batch_key": workspace_id, "kind": VALIDATOR_SCHEDULE_KIND,
                "candidate_id": user_id, "status": "pending", "attempts": 0, "created_at": now, "next_attempt_at": now,
                "payload": {"email": user.email, "formation": title},
            }}, upsert=True))
        if operations:
            self._insert_jobs(EmailJob._get_collection(), operations)
        return {**self.summarize(EmailJob.objects(kind=VALIDATOR_SCHEDULE_KIND, batch_key=workspace_id)),
                "queued_now": len(operations), "unchanged": unchanged}

    @staticmethod
    def prepare(job, _now):
        user = User.objects(id=job.candidate_id, is_active=True).only("first_name", "last_name", "email").first()
        workspace = InterviewCampaign.objects(id=job.batch_key).only("distribution").first()
        item = workspace.distribution["validators"].get(job.candidate_id) if workspace else None
        if not user or not item or user.email != job.payload.get("email") or not item["candidates"]:
            return None
        config = workspace.distribution
        names = {str(candidate.id): f"{candidate.first_name} {candidate.last_name}"
                 for candidate in Candidature.objects(id__in=item["candidates"]).only("first_name", "last_name")}
        rows = []
        for at, candidate_id in ValidatorScheduleOutbox._planning(config, item):
            minutes = ReferentialInterviews.candidate_time(config, item, candidate_id)[1]
            when = datetime.fromisoformat(at).strftime("%d/%m/%Y %Hh%M") if at else "À planifier"
            rows.append(f"<tr><td style=\"padding:4px 12px 4px 0\">{escape(when)}</td>"
                        f"<td style=\"padding:4px 12px 4px 0\">{escape(names.get(candidate_id, 'Candidat'))}</td>"
                        f"<td style=\"padding:4px 0\">{minutes or ''} min</td></tr>")
        name = escape(f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email)
        team = escape(_teams_url(item["teams_url"]), quote=True)
        formation = escape(job.payload["formation"])
        html = (f"<p>Bonjour {name},</p>"
                f"<p>Voici votre planning d’entretiens pour le référentiel {formation} ({len(rows)} candidat(s)), heure de Dakar.</p>"
                f'<p><a href="{team}">Votre réunion Microsoft Teams</a> : le même lien sert pour tous vos candidats, '
                "admettez-les depuis la salle d’attente à leur tour.</p>"
                "<table style=\"border-collapse:collapse\"><thead><tr><th align=\"left\">Horaire</th><th align=\"left\">Candidat</th>"
                f"<th align=\"left\">Durée</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
                "<p>Les fiches d’évaluation sont disponibles dans l’espace « Mes entretiens » de la plateforme ODC Admin.</p>"
                "<p>Orange Digital Center Sénégal</p>")
        return [user.email], f"Votre planning d’entretiens – {job.payload['formation']}", html

    @staticmethod
    def on_accepted(_job, _now):
        pass
