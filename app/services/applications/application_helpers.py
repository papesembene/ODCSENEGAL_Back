"""Shared validation and file handling for startup applications."""

from datetime import datetime
import os
import re

from werkzeug.utils import secure_filename


class ApplicationValidationError(ValueError):
    pass


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ALLOWED_DOCUMENT_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx"}
MAX_FILE_SIZE = 250 * 1024 * 1024


def validate_common_fields(data, required_fields):
    missing = [field for field in required_fields if not data.get(field)]
    if missing:
        raise ApplicationValidationError(
            f"Champs requis manquants: {', '.join(missing)}"
        )
    conditional = (
        ("role", "Autre", "otherRole", "Précisez votre rôle"),
        ("diploma", "autre", "otherDiploma", "Précisez votre diplôme"),
        (
            "sector",
            "other",
            "otherSector",
            "Précisez votre secteur d'activité",
        ),
        (
            "legalForm",
            "Autre",
            "otherLegalForm",
            "Précisez votre forme juridique",
        ),
    )
    for source, expected, target, message in conditional:
        if data.get(source) == expected and not data.get(target):
            raise ApplicationValidationError(message)
    if data.get("raisedFunds") == "Oui" and not data.get("raisedAmount"):
        raise ApplicationValidationError(
            "Le montant levé est obligatoire"
        )


def validate_email(value, label="Format email invalide"):
    if not value or not EMAIL_PATTERN.match(value):
        raise ApplicationValidationError(label)


def validate_phone(value):
    if len(re.sub(r"[^\d]", "", value or "")) < 8:
        raise ApplicationValidationError(
            "Le téléphone doit contenir au moins 8 chiffres"
        )


def validate_creation_date(value):
    try:
        creation_date = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError) as error:
        raise ApplicationValidationError(
            "Date de création invalide ou dans le futur"
        ) from error
    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if creation_date > today:
        raise ApplicationValidationError(
            "Date de création invalide ou dans le futur"
        )


def validate_document(file, missing_message, size_message):
    if not file or not getattr(file, "filename", ""):
        raise ApplicationValidationError(missing_message)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        raise ApplicationValidationError(size_message)
    extension = os.path.splitext(file.filename)[1].lower().lstrip(".")
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ApplicationValidationError(
            "Format de fichier non autorisé"
        )


def save_document(file, upload_folder, timestamp):
    os.makedirs(upload_folder, exist_ok=True)
    filename = f"{timestamp}_{secure_filename(file.filename)}"
    path = os.path.join(upload_folder, filename)
    file.save(path)
    return path


def remove_files(paths):
    for path in paths:
        if path and os.path.exists(path):
            os.remove(path)
