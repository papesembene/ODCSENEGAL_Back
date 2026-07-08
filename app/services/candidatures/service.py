"""Use cases for public and administrative candidatures."""

from datetime import datetime

from mongoengine.errors import NotUniqueError, ValidationError

from app.repositories.candidature_repository import CandidatureRepository
from app.services.candidatures.campaign_service import (
    CandidatureCampaignService,
    CandidatureCampaignServiceError,
)
from app.utils.request_guards import normalize_email, normalize_phone


class CandidatureServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class CandidatureService:
    REQUIRED_FIELDS = (
        "first_name",
        "last_name",
        "email",
        "phone",
        "date_of_birth",
        "place_of_birth",
        "gender",
        "cni_or_passport_number",
        "nationality",
        "region_of_residence",
        "computer_skills",
        "available_for_10_months",
        "desired_training",
        "accept_conditions",
    )
    BOOLEAN_FIELDS = {
        "computer_skills",
        "available_for_10_months",
        "accept_conditions",
    }
    UPDATE_FIELDS = (
        "status",
        "admin_notes",
        "interview_date",
        "score",
        "first_name",
        "last_name",
        "phone",
        "email",
        "desired_training",
        "region_of_residence",
    )
    REFERENTIALS = (
        "Dev Web",
        "Data",
        "Hackeuse",
        "AWS",
        "Design UX/UI",
    )

    def __init__(self, repository=None, now=None, campaign_service=None):
        self.repository = repository or CandidatureRepository()
        self.now = now or datetime.utcnow
        self.campaign_service = campaign_service or CandidatureCampaignService()

    def submit(self, data):
        self._validate_submission(data)
        self._assert_submission_open(data.get("desired_training"))
        email = normalize_email(data["email"])
        phone = normalize_phone(data["phone"])

        if self.repository.find_by_email(email):
            raise CandidatureServiceError(
                "Un utilisateur avec cet email existe déjà",
            )
        if self.repository.find_by_identity_number(
            data["cni_or_passport_number"],
        ):
            raise CandidatureServiceError(
                "Un utilisateur avec ce numéro CNI/passeport existe déjà",
            )

        candidature = self.repository.create(
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=email,
            phone=phone,
            date_of_birth=data["date_of_birth"],
            place_of_birth=data["place_of_birth"],
            gender=data["gender"],
            cni_or_passport_number=data["cni_or_passport_number"],
            nationality=data["nationality"],
            region_of_residence=data["region_of_residence"],
            current_structure=data.get("current_structure", ""),
            education_level=data.get("education_level", ""),
            computer_skills=data["computer_skills"],
            available_for_10_months=data["available_for_10_months"],
            desired_training=data["desired_training"],
            accept_conditions=data["accept_conditions"],
            speciality=data.get("speciality", ""),
            is_working=data.get("is_working", False),
            contract_type=data.get("contract_type", ""),
        )
        try:
            return self.repository.save(candidature)
        except NotUniqueError as error:
            raise CandidatureServiceError(
                "Une candidature avec cet email ou ce numéro de pièce "
                "existe déjà",
                409,
            ) from error

    def _assert_submission_open(self, desired_training):
        try:
            self.campaign_service.assert_open(desired_training)
        except CandidatureCampaignServiceError as error:
            raise CandidatureServiceError(str(error), error.status_code) from error
        except ValidationError as error:
            raise CandidatureServiceError(
                f"Erreur de validation des données : {error}",
            ) from error

    def check_unique(self, field, value):
        if not field or not value:
            raise CandidatureServiceError(
                "Les paramètres field et value sont requis",
            )
        if field == "email":
            return bool(
                self.repository.find_by_email(normalize_email(value)),
            )
        if field == "cni_or_passport_number":
            return bool(
                self.repository.find_by_identity_number(value),
            )
        raise CandidatureServiceError(
            "Champ non valide pour vérification",
        )

    def list_candidatures(
        self,
        desired_training=None,
        status=None,
        search="",
        page=None,
        per_page=None,
    ):
        filters = {}
        if desired_training and desired_training != "all":
            filters["desired_training"] = desired_training
        if status and status != "all":
            filters["status"] = status
        candidatures = self.repository.list_filtered(
            filters,
            search,
            page=page,
            per_page=per_page,
        )
        total = self.repository.count_filtered(filters, search)
        return {
            "data": [item.to_dict() for item in candidatures],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    def get_candidature(self, candidature_id):
        candidature = self.repository.get(candidature_id)
        if not candidature:
            raise CandidatureServiceError(
                "Candidature non trouvée",
                404,
            )
        return candidature

    def update_candidature(self, candidature_id, data):
        candidature = self.get_candidature(candidature_id)
        for field in self.UPDATE_FIELDS:
            if field in data:
                setattr(candidature, field, data[field])
        candidature.updated_at = self.now()
        try:
            return self.repository.save(candidature)
        except ValidationError as error:
            raise CandidatureServiceError(
                f"Erreur de validation : {error}",
            ) from error

    def delete_candidature(self, candidature_id):
        candidature = self.get_candidature(candidature_id)
        self.repository.delete(candidature)

    def get_statistics(self, desired_training=None):
        candidatures = self.repository.list_for_training(desired_training)
        referential_stats = {}
        for referential in self.REFERENTIALS:
            referential_items = self.repository.list_for_training(
                referential,
            )
            referential_stats[referential] = self._status_counts(
                referential_items,
            )
        return {
            **self._status_counts(candidatures),
            "referentielStats": referential_stats,
        }

    def prepare_email_batch(self, data):
        candidate_ids = data.get("candidateIds", [])
        if not candidate_ids:
            raise CandidatureServiceError(
                "Aucun candidat sélectionné",
            )
        candidatures = self.repository.list_by_ids(candidate_ids)
        count = candidatures.count()
        email_type = data.get("emailType")
        labels = {
            "interview_invitation": "d'invitation à l'entretien",
            "acceptance": "d'acceptation",
            "rejection": "de refus",
            "information": "d'information",
        }
        return {
            "message": (
                f"Email {labels.get(email_type, '')} envoyé à "
                f"{count} candidat(s)"
            ),
            "emails": [item.email for item in candidatures],
            "custom_message": data.get("customMessage", ""),
            "sent": count,
            "type": email_type,
            "timestamp": self.now().isoformat(),
        }

    def _validate_submission(self, data):
        if not data:
            raise CandidatureServiceError("Données manquantes")
        for field in self.REQUIRED_FIELDS:
            if field not in data:
                raise CandidatureServiceError(
                    f"Le champ {field} est requis",
                )
            if field in self.BOOLEAN_FIELDS:
                if not isinstance(data[field], bool):
                    raise CandidatureServiceError(
                        f"Le champ {field} doit être un booléen",
                    )
            elif not data[field]:
                raise CandidatureServiceError(
                    f"Le champ {field} est requis",
                )

    @staticmethod
    def _status_counts(query):
        return {
            "total": query.count(),
            "pending": query.filter(status="pending").count(),
            "accepted": query.filter(status="accepted").count(),
            "rejected": query.filter(status="rejected").count(),
            "interview": query.filter(status="interview").count(),
        }
