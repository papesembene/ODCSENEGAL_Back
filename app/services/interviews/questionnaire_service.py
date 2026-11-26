"""Persist campaign banks and candidate-specific interview questionnaires."""

from datetime import datetime
from uuid import UUID

from bson import ObjectId
from mongoengine import Q

from app.models.candidature import Candidature
from app.models.candidature_campaign import CandidatureCampaign
from app.models.interview import InterviewCampaign, InterviewEvaluation, InterviewSlot
from app.models.user import User
from app.services.interviews.access_policy import is_interview_member, slot_roles
from app.services.interviews.exceptions import (
    InterviewConflictError, InterviewForbiddenError, InterviewNotFoundError, InterviewValidationError,
)
from app.services.interviews.questionnaire import (
    PROFILES, config_weights, generate_questions, grade_answers, is_multiple, normalize_config, question_groups, review_answers,
    validate_bank,
)


class InterviewQuestionnaireService:
    @staticmethod
    def _campaign(campaign_id):
        campaign = InterviewCampaign.objects(id=campaign_id).first() if ObjectId.is_valid(campaign_id) else None
        if not campaign or not campaign.uses_questionnaire:
            raise InterviewNotFoundError("Campagne d’entretien direct introuvable.")
        return campaign

    def get_bank(self, campaign_id):
        campaign = self._campaign(campaign_id)
        return self._bank_payload(campaign.question_bank, campaign.question_bank_revision, campaign)

    @staticmethod
    def _config(campaign):
        try:
            return normalize_config(campaign.questionnaire_config or None)
        except InterviewValidationError:
            return normalize_config(None)

    @classmethod
    def _coverage_error(cls, questions, campaign):
        try:
            for profile in PROFILES:
                question_groups(questions, profile, cls._config(campaign))
        except InterviewValidationError as error:
            return str(error)
        return None

    def _bank_payload(self, questions, revision, campaign):
        return {"questions": questions, "errors": [], "revision": revision, "config": self._config(campaign),
                "coverage_error": self._coverage_error(questions, campaign) if questions else None}

    def update_config(self, campaign_id, data):
        """Store the question count and weight of each section; generated questionnaires keep their snapshot."""
        campaign = self._campaign(campaign_id)
        if not isinstance(data, dict):
            raise InterviewValidationError("Configuration du questionnaire invalide.")
        config = normalize_config(data.get("config"))
        InterviewCampaign.objects(id=campaign.id).update_one(set__questionnaire_config=config, set__updated_at=datetime.utcnow())
        campaign.questionnaire_config = config
        return self._bank_payload(campaign.question_bank, campaign.question_bank_revision, campaign)

    def process_bank(self, campaign_id, data, *, save):
        campaign = self._campaign(campaign_id)
        if not isinstance(data, dict):
            raise InterviewValidationError("Import de questions invalide.")
        rows = data.get("questions")
        mode = data.get("mode", "replace")
        if mode not in ("replace", "append"):
            raise InterviewValidationError("Mode d’import invalide.")
        questions, errors = validate_bank(rows)
        if errors:
            return {"questions": questions, "errors": errors}
        imported = questions
        if mode == "append":
            prefix = campaign.question_bank
            questions, errors = validate_bank([*prefix, *imported])
            errors = [{**error, "index": index - len(prefix) if (index := error["index"]) >= len(prefix) else None}
                      for error in errors]
        coverage_error = self._coverage_error(questions, campaign)
        if coverage_error and mode == "replace" and not errors:
            errors.append({"index": None, "message": coverage_error})
        if errors or not save:
            return {"questions": imported, "errors": errors, "coverage_error": coverage_error}
        return self._save_bank(campaign, questions, data.get("revision"))

    def edit_bank(self, campaign_id, data):
        campaign = self._campaign(campaign_id)
        if not isinstance(data, dict):
            raise InterviewValidationError("Modification de question invalide.")
        revision = data.get("revision")
        self._check_bank_revision(campaign, revision)
        questions = list(campaign.question_bank)
        action = data.get("action")
        index = data.get("index")
        if action == "add":
            questions.append(data.get("question"))
        elif action in ("edit", "set_active"):
            if type(index) is not int or not 0 <= index < len(questions):
                raise InterviewNotFoundError("Question introuvable.")
            if action == "edit":
                question = data.get("question")
                if not isinstance(question, dict):
                    raise InterviewValidationError("Modification de question invalide.")
                questions[index] = {**question, "active": questions[index].get("active", True)}
            else:
                active = data.get("active")
                if type(active) is not bool:
                    raise InterviewValidationError("Statut de question invalide.")
                questions[index] = {**questions[index], "active": active}
        else:
            raise InterviewValidationError("Action de question inconnue.")
        questions, errors = validate_bank(questions)
        if errors:
            raise InterviewValidationError(errors[0]["message"])
        return self._save_bank(campaign, questions, revision)

    @staticmethod
    def _check_bank_revision(campaign, revision):
        if type(revision) is not int or revision != campaign.question_bank_revision:
            raise InterviewConflictError("La banque a changé. Actualisez-la avant de réessayer.")

    def _save_bank(self, campaign, questions, revision):
        self._check_bank_revision(campaign, revision)
        condition = Q(question_bank_revision=revision)
        if revision == 0:
            condition |= Q(question_bank_revision__exists=False)
        if not InterviewCampaign.objects(condition, id=campaign.id).update_one(
            set__question_bank=questions, set__question_bank_revision=revision + 1, set__updated_at=datetime.utcnow(),
        ):
            raise InterviewConflictError("La banque a changé. Actualisez-la avant de réessayer.")
        return self._bank_payload(questions, revision + 1, campaign)

    def _evaluation(self, evaluation_id, admin, *, write):
        evaluation = InterviewEvaluation.objects(id=evaluation_id).first() if ObjectId.is_valid(evaluation_id) else None
        if not evaluation:
            raise InterviewNotFoundError("Évaluation introuvable.")
        campaign = self._campaign(evaluation.campaign_id)
        if is_interview_member(admin):
            slot = InterviewSlot.objects(id=evaluation.slot_id, campaign_id=evaluation.campaign_id).first() if evaluation.slot_id else None
            if "validator" not in slot_roles(slot, admin):
                raise InterviewForbiddenError("Cette évaluation n’est pas attribuée à votre compte de validateur.")
            if write and slot.status == "cancelled":
                raise InterviewConflictError("Ce créneau a été annulé.")
            if write and self.is_archived(campaign):
                raise InterviewForbiddenError("La campagne est archivée : la fiche est consultable en lecture seule.")
        # Platform administrators may complete or correct any evaluation, including in an archived campaign.
        return evaluation, campaign

    @staticmethod
    def is_archived(campaign):
        """Validators lose write access once the candidature campaign is archived (a closed campaign keeps interviews open)."""
        if not campaign.candidature_campaign_id or not ObjectId.is_valid(campaign.candidature_campaign_id):
            return False
        source = CandidatureCampaign.objects(id=campaign.candidature_campaign_id).only("status").first()
        return bool(source and source.status == "archived")

    @staticmethod
    def _serialize(questionnaire):
        return {
            **{key: value for key, value in questionnaire.items() if key not in {"draft_session", "draft_sequence"}},
            # The right letters stay on the server; the screen only needs to know if several are expected.
            "questions": [
                {**{key: value for key, value in question.items() if key != "correct"}, "multiple": is_multiple(question)}
                for question in questionnaire.get("questions", [])
            ],
        }

    @staticmethod
    def _feedback(questionnaire):
        answers = questionnaire.get("answers", {})
        questions = [item for item in questionnaire.get("questions", []) if item["options"] and item["id"] in answers]
        return {key: {**mark, "answer": answers[key]} for key, mark in review_answers(questions, answers).items()}

    @staticmethod
    def declared_profile(evaluation):
        """Computer profile declared on the application form ("Notions en informatique"), or None if unknown."""
        candidate = Candidature.objects(id=evaluation.candidature_id).only("computer_skills").first() \
            if ObjectId.is_valid(evaluation.candidature_id) else None
        skills = getattr(candidate, "computer_skills", None)
        return None if skills is None else ("avec" if skills else "sans")

    def get(self, evaluation_id, admin):
        evaluation, campaign = self._evaluation(evaluation_id, admin, write=False)
        questionnaire = evaluation.questionnaire
        payload = self._serialize(questionnaire)
        payload["declared_profile"] = self.declared_profile(evaluation)
        payload["read_only"] = is_interview_member(admin) and self.is_archived(campaign)
        if admin is not None and not is_interview_member(admin) and questionnaire:
            actor_id = questionnaire.get("last_saved_by") or questionnaire.get("finalized_by")
            actor = User.objects(id=actor_id).only("first_name", "last_name", "email").first() if ObjectId.is_valid(actor_id) else None
            name = (" ".join(filter(None, (actor.first_name, actor.last_name))) or actor.email) if actor else None
            payload["review"] = {
                "questions": review_answers(questionnaire.get("questions", []), questionnaire.get("answers", {})),
                "reviewer": name,
                "saved_at": questionnaire.get("last_saved_at") or questionnaire.get("finalized_at"),
            }
        elif questionnaire.get("answers"):
            payload["feedback"] = self._feedback(questionnaire)
        return payload

    def check_answer(self, evaluation_id, data, admin):
        evaluation, _ = self._evaluation(evaluation_id, admin, write=True)
        if not isinstance(data, dict):
            raise InterviewValidationError("Choisissez une réponse au QCM.")
        questionnaire = evaluation.questionnaire
        revision = data.get("revision")
        if questionnaire.get("status") != "draft" or type(revision) is not int or not 1 <= revision <= questionnaire.get("revision", 0):
            raise InterviewConflictError("Le questionnaire a changé. Actualisez la fiche.")
        question_id = data.get("question_id")
        question = next((item for item in questionnaire.get("questions", []) if item["id"] == question_id and item["options"]), None)
        if not question:
            raise InterviewValidationError("Cette question ne fait pas partie de ce questionnaire.")
        answers, _ = grade_answers([question], {question["id"]: data.get("answer")}, complete=False)
        return {**review_answers([question], answers)[question["id"]], "answer": answers[question["id"]]}

    @staticmethod
    def _cas_query(evaluation, revision):
        condition = Q(questionnaire__revision=revision) if revision else Q(questionnaire__revision__exists=False)
        return InterviewEvaluation.objects(condition, id=evaluation.id, slot_id=evaluation.slot_id)

    def generate(self, evaluation_id, data, admin):
        evaluation, campaign = self._evaluation(evaluation_id, admin, write=True)
        if evaluation.questionnaire.get("status"):
            return self._serialize(evaluation.questionnaire)
        if not isinstance(data, dict):
            raise InterviewValidationError("Paramètres de génération invalides.")
        # The application form already asked whether the candidate did computing: no need to ask again.
        profile = self.declared_profile(evaluation) or data.get("profile")
        revision = evaluation.questionnaire.get("revision", 0)
        config = self._config(campaign)
        questionnaire = {
            "profile": profile, "questions": generate_questions(campaign.question_bank, profile, config), "config": config,
            "revision": revision + 1, "status": "draft", "answers": {}, "comment": "",
        }
        if not self._cas_query(evaluation, revision).update_one(
            set__questionnaire=questionnaire, set__updated_at=datetime.utcnow(),
        ):
            evaluation, _ = self._evaluation(evaluation_id, admin, write=True)
            if not evaluation.questionnaire.get("status"):
                raise InterviewConflictError("L’affectation a changé. Actualisez la page.")
            questionnaire = evaluation.questionnaire
        return self._serialize(questionnaire)

    def save(self, evaluation_id, data, admin, *, retries=3):
        if not isinstance(data, dict):
            raise InterviewValidationError("Évaluation invalide.")
        action = data.get("action")
        if action not in ("draft", "validate", "absent", "reopen"):
            raise InterviewValidationError("Action inconnue.")
        admin_reopen = action == "reopen"
        if admin_reopen and is_interview_member(admin):
            raise InterviewForbiddenError("La réouverture est réservée aux administrateurs.")
        evaluation, _ = self._evaluation(evaluation_id, admin, write=not admin_reopen)
        questionnaire = dict(evaluation.questionnaire)
        revision = questionnaire.get("revision", 0)
        client_revision = data.get("revision")
        session = data.get("draft_session") if action == "draft" else None
        sequence = data.get("draft_sequence")
        same_session = False
        if session is not None:
            try:
                session = str(UUID(session))
            except (ValueError, TypeError, AttributeError) as error:
                raise InterviewValidationError("Session de brouillon invalide.") from error
            if type(sequence) is not int or not 1 <= sequence <= 2147483647:
                raise InterviewValidationError("Version de brouillon invalide.")
            same_session = (
                questionnaire.get("status") == "draft" and questionnaire.get("draft_session") == session
                and questionnaire.get("last_saved_by") == str(admin.id)
            )
        if type(client_revision) is not int or client_revision > revision or (client_revision != revision and not same_session):
            raise InterviewConflictError("L’évaluation a changé. Actualisez la fiche.")
        if same_session and sequence <= questionnaire.get("draft_sequence", 0):
            return {**self._serialize(questionnaire), "feedback": self._feedback(questionnaire)}
        is_closed = questionnaire.get("status") in {"validated", "absent"}
        if admin_reopen != is_closed:
            raise InterviewConflictError("Cette action ne correspond pas à l’état actuel de l’évaluation.")
        if admin_reopen and evaluation.final_status != "en_attente":
            raise InterviewConflictError("Retirez la décision finale avant de rouvrir cette évaluation.")
        if admin_reopen and ((InterviewCampaign.objects(id=evaluation.campaign_id).only("preselection").first().preselection or {})
                             .get("status") == "validated"):
            raise InterviewConflictError("La présélection de ce référentiel est validée : l’évaluation ne peut plus être rouverte.")

        complete = action == "validate"
        status = {"validate": "validated", "absent": "absent"}.get(action, "draft")
        if action in {"draft", "validate"}:
            if not questionnaire.get("questions"):
                raise InterviewValidationError("Générez le questionnaire avant de saisir les réponses.")
            answers, scores = grade_answers(
                questionnaire["questions"], data.get("answers"), complete=complete, weights=config_weights(questionnaire.get("config")),
            )
            comment = data.get("comment", "")
            if not isinstance(comment, str) or len(comment) > 3000:
                raise InterviewValidationError("L’appréciation doit contenir au plus 3 000 caractères.")
            questionnaire.update(answers=answers, scores=scores, comment=comment.strip())
        if admin_reopen:
            questionnaire.pop("scores", None)
            questionnaire.pop("finalized_by", None)
            questionnaire.pop("finalized_at", None)
            if not questionnaire.get("questions"):
                status = None

        now = datetime.utcnow()
        if not admin_reopen:
            questionnaire.update(last_saved_by=str(admin.id), last_saved_at=now.isoformat() + "Z")
        if status in {"validated", "absent"}:
            questionnaire.update(finalized_by=str(admin.id), finalized_at=now.isoformat() + "Z")
        if session is not None:
            questionnaire.update(draft_session=session, draft_sequence=sequence)
        else:
            questionnaire.pop("draft_session", None)
            questionnaire.pop("draft_sequence", None)
        questionnaire.update(status=status, revision=revision + 1)
        query = self._cas_query(evaluation, revision)
        if admin_reopen:
            query = query.filter(final_status="en_attente")
        if not query.update_one(
            set__questionnaire=questionnaire, set__is_complete=complete,
            set__is_locked=status in {"validated", "absent"},
            set__interview_progress_status={"validated": "passe", "absent": "absent"}.get(status, "planifie"),
            set__updated_at=now,
        ):
            if session is not None and retries:
                return self.save(evaluation_id, data, admin, retries=retries - 1)
            raise InterviewConflictError("L’évaluation a changé. Actualisez la fiche.")
        if admin_reopen:
            return self.get(evaluation_id, admin)
        return {**self._serialize(questionnaire), "feedback": self._feedback(questionnaire)}
