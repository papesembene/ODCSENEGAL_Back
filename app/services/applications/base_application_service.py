"""Shared orchestration for startup-program applications."""

from datetime import datetime
import os

from mongoengine.errors import NotUniqueError, ValidationError

from app.services.applications.application_helpers import (
    ApplicationValidationError,
    remove_files,
    save_document,
    validate_common_fields,
    validate_creation_date,
    validate_document,
    validate_email,
    validate_phone,
)
from app.utils.request_guards import normalize_email, normalize_phone


class DuplicateApplicationError(ApplicationValidationError):
    status_code = 409


class ApplicationPersistenceError(ApplicationValidationError):
    pass


class BaseApplicationService:
    required_fields = ()
    cv_field = "cv"
    pitch_field = "pitch_deck"
    validate_company_creation_date = False

    def __init__(self, model, upload_folder):
        self.model = model
        self.upload_folder = upload_folder

    def email_exists(self, email):
        normalized_email = normalize_email(email)
        return bool(
            normalized_email
            and self.model.check_email_exists(normalized_email)
        )

    def phone_exists(self, phone):
        normalized_phone = normalize_phone(phone)
        return bool(
            normalized_phone
            and self.model.check_phone_exists(normalized_phone)
        )

    def submit(self, form_data, files):
        data = dict(form_data)
        validate_common_fields(data, self.required_fields)
        self._normalize_and_validate_identity(data)
        if self.validate_company_creation_date:
            validate_creation_date(data.get("creationDate"))

        cv_file = files.get("cv")
        pitch_file = files.get("pitch_deck")
        validate_document(
            cv_file,
            "CV requis",
            "Le CV est trop volumineux (max 250MB)",
        )
        validate_document(
            pitch_file,
            "Document de présentation requis",
            "Le document de présentation est trop volumineux (max 250MB)",
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_paths = []
        try:
            cv_path = save_document(
                cv_file,
                self.upload_folder,
                timestamp,
            )
            saved_paths.append(cv_path)
            pitch_path = save_document(
                pitch_file,
                self.upload_folder,
                timestamp,
            )
            saved_paths.append(pitch_path)

            data[self.cv_field] = cv_path
            data[self.pitch_field] = pitch_path
            data["acceptTerms"] = data.get("acceptTerms") == "true"
            data["createdAt"] = datetime.utcnow()
            self.prepare_model_data(data)

            application = self.model(**data)
            application.save()
            return application
        except NotUniqueError as error:
            remove_files(saved_paths)
            raise DuplicateApplicationError(
                "Une candidature avec cet email ou ce téléphone existe déjà"
            ) from error
        except ValidationError as error:
            remove_files(saved_paths)
            raise ApplicationPersistenceError(
                f"Erreur de validation: {error}"
            ) from error
        except Exception:
            remove_files(saved_paths)
            raise

    def delete(self, application):
        remove_files(
            [
                getattr(application, self.cv_field, None),
                getattr(application, self.pitch_field, None),
            ]
        )
        application.delete()

    def prepare_model_data(self, data):
        """Hook for program-specific compatibility fields."""

    def build_email_data(self, application):
        return {
            "firstName": application.firstName,
            "lastName": application.lastName,
            "email": application.email,
            "companyName": application.companyName,
            "sector": application.sector,
            "productName": application.productName,
            "created_at": application.createdAt,
        }

    def _normalize_and_validate_identity(self, data):
        normalized_email = normalize_email(data.get("email"))
        validate_email(normalized_email)
        if self.model.check_email_exists(normalized_email):
            raise ApplicationValidationError(
                "Cet email a déjà été utilisé pour une candidature"
            )
        data["email"] = normalized_email

        alternate_email = normalize_email(data.get("emailAlternate"))
        if alternate_email:
            validate_email(
                alternate_email,
                "Format email alternatif invalide",
            )
            if alternate_email == normalized_email:
                raise ApplicationValidationError(
                    "L'email alternatif doit être différent de l'email principal"
                )
            data["emailAlternate"] = alternate_email

        normalized_phone = normalize_phone(data.get("phone"))
        validate_phone(normalized_phone)
        full_phone = f"{data.get('phoneCountry', '')}{normalized_phone}"
        if self.model.check_phone_exists(full_phone):
            raise ApplicationValidationError(
                "Ce numéro de téléphone a déjà été utilisé pour une candidature"
            )
        data["phone"] = normalized_phone
        data["fullPhone"] = full_phone


def absolute_upload_folder(root_path, relative_folder):
    if os.path.isabs(relative_folder):
        return relative_folder
    return os.path.join(root_path, relative_folder)
