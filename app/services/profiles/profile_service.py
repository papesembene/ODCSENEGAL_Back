"""Registration and profile update use cases."""

import os
from uuid import uuid4

from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from app.models.user import (
    CorporateInvestorProfile,
    FileField,
    StartupProfile,
    StudentProfile,
)
from app.repositories.user_repository import UserRepository


class ProfileValidationError(ValueError):
    pass


class ProfileService:
    PROFILE_DEFINITIONS = {
        "student": {
            "attribute": "student_profile",
            "factory": StudentProfile,
            "fields": {
                "institution": "institution",
                "educationLevel": "education_level",
                "sector": "sector",
                "motivations": "motivations",
                "interests": "interests",
            },
            "files": {
                "cv_file": ("cv_file", "students/cv"),
                "cover_letter_file": (
                    "cover_letter_file",
                    "students/cover_letters",
                ),
            },
        },
        "startup": {
            "attribute": "startup_profile",
            "factory": StartupProfile,
            "fields": {
                "companyName": "company_name",
                "companySector": "company_sector",
                "location": "location",
                "valueProposition": "value_proposition",
                "maturityStage": "maturity_stage",
                "foundingTeam": "founding_team",
                "needs": "needs",
            },
            "files": {
                "logo_file": ("logo_file", "startups/logos"),
                "pitch_deck_file": (
                    "pitch_deck_file",
                    "startups/pitch_decks",
                ),
                "business_plan_file": (
                    "business_plan_file",
                    "startups/business_plans",
                ),
            },
        },
        "corporate": {
            "attribute": "corporate_investor_profile",
            "factory": CorporateInvestorProfile,
            "fields": {
                "organizationName": "organization_name",
                "activities": "activities",
                "interestSectors": "interest_sectors",
                "cooperationObjectives": "cooperation_objectives",
            },
            "files": {
                "brochure_file": (
                    "brochure_file",
                    "corporate/brochures",
                ),
            },
        },
    }
    PROFILE_DEFINITIONS["investor"] = PROFILE_DEFINITIONS["corporate"]

    def __init__(self, repository=None):
        self.repository = repository or UserRepository()

    def register(self, data, files, upload_folder):
        data = data or {}
        required_fields = ("email", "password", "profileType")
        if not all(field in data for field in required_fields):
            raise ProfileValidationError(
                "Email, mot de passe et type de profil requis"
            )
        if self.repository.find_by_email(data["email"]):
            raise ProfileValidationError(
                "Un utilisateur avec cet email existe déjà"
            )

        profile_type = data["profileType"]
        if profile_type not in self.PROFILE_DEFINITIONS:
            raise ProfileValidationError("Type de profil invalide")

        user = self.repository.create(
            email=data["email"],
            password_hash=generate_password_hash(data["password"]),
            profile_type=profile_type,
            first_name=data.get("firstName", ""),
            last_name=data.get("lastName", ""),
            is_active=True,
        )
        profile_data = self._apply_profile(
            user,
            data,
            files or {},
            upload_folder,
            create=True,
        )
        user.profile_data = profile_data
        return self.repository.save(user)

    def update(self, user, data, files, upload_folder):
        data = data or {}
        files = files or {}
        if "email" in data:
            user.email = data["email"]
        if "firstName" in data:
            user.first_name = data["firstName"]
        if "lastName" in data:
            user.last_name = data["lastName"]

        self._apply_profile(
            user,
            data,
            files,
            upload_folder,
            create=False,
        )
        return self.repository.save(user)

    def serialize(self, user):
        payload = user.to_json()
        profile = self._get_profile(user)
        if profile:
            payload["profile_data"] = self._serialize_profile(profile)
        return payload

    def serialize_update_response(self, user):
        profile = self._get_profile(user)
        return {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "profile_type": user.profile_type,
            "profile_data": (
                self._serialize_profile(profile) if profile else {}
            ),
        }

    def _apply_profile(
        self,
        user,
        data,
        files,
        upload_folder,
        create,
    ):
        definition = self.PROFILE_DEFINITIONS[user.profile_type]
        attribute = definition["attribute"]
        profile = getattr(user, attribute, None)
        if create or profile is None:
            values = {
                target: data.get(source, "")
                for source, target in definition["fields"].items()
            }
            profile = definition["factory"](**values)
        else:
            for source, target in definition["fields"].items():
                if source in data:
                    setattr(profile, target, data[source])

        stored_paths = {}
        for input_name, (target, folder) in definition["files"].items():
            file = files.get(input_name)
            if not file or not getattr(file, "filename", ""):
                continue
            file_info = self._save_file(
                file,
                upload_folder,
                folder,
            )
            setattr(profile, target, FileField(**file_info))
            stored_paths[f"{target.replace('_file', '')}_path"] = (
                file_info["path"]
            )

        setattr(user, attribute, profile)
        return stored_paths

    @staticmethod
    def _save_file(file, upload_folder, subfolder):
        filename = secure_filename(file.filename)
        unique_name = f"{uuid4().hex}_{filename}"
        folder_path = os.path.join(upload_folder, subfolder)
        os.makedirs(folder_path, exist_ok=True)
        save_path = os.path.join(folder_path, unique_name)
        file.save(save_path)
        return {
            "filename": filename,
            "path": os.path.join(subfolder, unique_name),
            "content_type": file.content_type,
            "size": os.path.getsize(save_path),
        }

    def _get_profile(self, user):
        definition = self.PROFILE_DEFINITIONS.get(user.profile_type)
        return (
            getattr(user, definition["attribute"], None)
            if definition
            else None
        )

    @staticmethod
    def _serialize_profile(profile):
        payload = {}
        for field_name in profile._fields:
            value = getattr(profile, field_name, None)
            if isinstance(value, FileField):
                payload[field_name] = value.to_json()
            else:
                payload[field_name] = value
        return payload
